// Tablero SCADA del gemelo digital: recibe muestras por WebSocket y envía órdenes por REST.

const MAX_PUNTOS = 600; // 5 minutos a 2 muestras por segundo
const NOMBRES_FALLA = {
  sensor_pegado: "Sensor de nivel pegado",
  deriva: "Deriva del transmisor",
  cavitacion: "Cavitación de la bomba",
  valvula_trabada: "Válvula trabada",
};
const NOMBRES_RESIDUO = {
  r_balance: "balance masa",
  r_bomba: "caudal bomba",
  r_valvula: "caudal válvula",
  r_corriente: "corriente",
  r_presion: "presión",
  ruido_corriente: "ruido corriente",
};
const ESTADOS = {
  activa_no_reconocida: "Activa sin reconocer",
  activa_reconocida: "Activa reconocida",
  normalizada_no_reconocida: "Normalizada sin reconocer",
};

const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let verReal = false;
let usuarioMoviendo = false;

// ------------------------------------------------------------------ gráficas
Chart.defaults.font.family = "ui-monospace, Consolas, monospace";
Chart.defaults.font.size = 11;
Chart.defaults.animation = false;

function grafica(id, series, opcionesY = {}) {
  return new Chart($(id), {
    type: "line",
    data: { labels: [], datasets: series.map((s) => ({ pointRadius: 0, borderWidth: 1.5, tension: 0, ...s, data: [] })) },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { boxWidth: 12 } } },
      scales: {
        x: { ticks: { maxTicksLimit: 6 } },
        y: opcionesY,
      },
    },
  });
}

const gNivel = grafica("gNivel", [
  { label: "Nivel medido LT-101 [m]", borderColor: css("--pv") },
  { label: "Setpoint [m]", borderColor: css("--sp"), borderDash: [6, 4] },
  { label: "Nivel real [m]", borderColor: css("--alta"), hidden: true },
], { min: 0, max: 4 });
const gCaudal = grafica("gCaudal", [
  { label: "Entrada FT-101 [L/s]", borderColor: "#3d6f99" },
  { label: "Salida FT-102 [L/s]", borderColor: "#8a9096" },
], { min: 0 });
const gPuntaje = grafica("gPuntaje", [
  { label: "Puntaje del detector", borderColor: css("--pv") },
  { label: "Umbral", borderColor: css("--alta"), borderDash: [4, 4] },
], { min: 0.3, max: 0.9 });

for (const g of [gNivel, gCaudal, gPuntaje]) {
  g.options.scales.x.ticks.callback = function (v) { return Math.round(this.getLabelForValue(v)); };
}

function agregar(g, t, valores) {
  g.data.labels.push(t);
  valores.forEach((v, i) => g.data.datasets[i].data.push(v));
  if (g.data.labels.length > MAX_PUNTOS) {
    g.data.labels.shift();
    g.data.datasets.forEach((d) => d.data.shift());
  }
}

function graficar(m) {
  agregar(gNivel, m.t, [m.nivel, m.setpoint, m.nivel_real]);
  agregar(gCaudal, m.t, [m.caudal_entrada, m.caudal_salida]);
  agregar(gPuntaje, m.t, [m.puntaje ?? null, m.umbral ?? null]);
}

function refrescarGraficas() {
  gNivel.update("none");
  gCaudal.update("none");
  gPuntaje.update("none");
}

// ------------------------------------------------------------------ diagrama
const Y_FONDO = 258, ALTO = 216, ALTURA_M = 4;
const yNivel = (h) => Y_FONDO - (Math.min(Math.max(h, 0), ALTURA_M) / ALTURA_M) * ALTO;

function pintarProceso(m) {
  const y = yNivel(m.nivel_real ?? m.nivel);
  $("agua").setAttribute("y", y);
  $("agua").setAttribute("height", Y_FONDO - y);
  $("lineaSp").setAttribute("y1", yNivel(m.setpoint));
  $("lineaSp").setAttribute("y2", yNivel(m.setpoint));
  // el agua se dibuja con el nivel real; si no se quiere ver, se dibuja con el medido
  if (!verReal) {
    const ym = yNivel(m.nivel);
    $("agua").setAttribute("y", ym);
    $("agua").setAttribute("height", Y_FONDO - ym);
  }
  $("lineaReal").setAttribute("visibility", verReal ? "visible" : "hidden");
  $("lineaReal").setAttribute("y1", y);
  $("lineaReal").setAttribute("y2", y);

  $("pvTxt").textContent = m.nivel.toFixed(2);
  $("spTxt").textContent = m.setpoint.toFixed(2);
  $("outTxt").textContent = m.velocidad.toFixed(1);
  $("velTxt").textContent = m.velocidad.toFixed(1);
  $("qeTxt").textContent = m.caudal_entrada.toFixed(1);
  $("qsTxt").textContent = m.caudal_salida.toFixed(1);
  $("apTxt").textContent = m.apertura_cmd.toFixed(0);
  $("pTxt").textContent = m.presion.toFixed(1);
  $("iTxt").textContent = m.corriente.toFixed(2);
  $("tiempo").textContent = Math.round(m.t);
  $("modoTxt").textContent = m.modo === "auto" ? "AUTO" : "MANUAL";

  if (!usuarioMoviendo) {
    $("sp").value = m.setpoint; $("spOut").textContent = `${m.setpoint.toFixed(1)} m`;
    $("ap").value = m.apertura_cmd; $("apOut").textContent = `${Math.round(m.apertura_cmd)} %`;
  }
  $("btnAuto").classList.toggle("activo", m.modo === "auto");
  $("btnManual").classList.toggle("activo", m.modo === "manual");
  document.querySelectorAll(".falla").forEach((b) => b.classList.toggle("on", m.fallas.includes(b.dataset.tipo)));
}

// ------------------------------------------------------------------ detector
function pintarDetector(m) {
  const e = $("estadoDetector");
  e.textContent = m.anomalia ? "ANOMALÍA" : "NORMAL";
  e.classList.toggle("anomalia", !!m.anomalia);
  $("explicacion").textContent = m.anomalia
    ? m.explicacion
    : "El detector compara cada instrumento contra el modelo físico de la planta.";
  const z = m.zscores || {};
  $("barras").innerHTML = Object.keys(NOMBRES_RESIDUO).map((k) => {
    const v = z[k] ?? 0;
    const ancho = Math.min(Math.abs(v) / 10, 1) * 50;
    const izq = v >= 0 ? 50 : 50 - ancho;
    const fuera = Math.abs(v) > 4 ? "fuera" : "";
    return `<span>${NOMBRES_RESIDUO[k]}</span><div class="barra"><span class="${fuera}" style="left:${izq}%;width:${ancho}%"></span></div><span>${v.toFixed(1)}σ</span>`;
  }).join("");
}

// ------------------------------------------------------------------ alarmas y eventos
function pintarAlarmas(alarmas) {
  const cuerpo = $("tablaAlarmas");
  if (!alarmas.length) {
    cuerpo.innerHTML = '<tr><td colspan="4">Sin alarmas</td></tr>';
  } else {
    cuerpo.innerHTML = alarmas.map((a) => `
      <tr class="${a.estado.includes("no_reconocida") ? "no_reconocida" : ""}">
        <td><span class="prio ${a.prioridad}"></span>${a.tag}</td>
        <td>${a.descripcion}</td>
        <td>${ESTADOS[a.estado] ?? a.estado}</td>
        <td>${a.estado.includes("no_reconocida") ? `<button data-tag="${a.tag}">Reconocer</button>` : ""}</td>
      </tr>`).join("");
  }
  const sinReconocer = alarmas.filter((a) => a.estado === "activa_no_reconocida");
  const banda = $("banda");
  if (sinReconocer.length) {
    const peor = sinReconocer[0];
    banda.style.display = "block";
    banda.className = peor.prioridad === "alta" ? "" : "media";
    banda.textContent = `${peor.tag} · ${peor.descripcion}`;
  } else {
    banda.style.display = "none";
  }
}

function agregarEvento(ev) {
  const div = document.createElement("div");
  div.className = ev.tipo;
  div.textContent = `t=${Math.round(ev.t)} s  ${ev.tag}  ${ev.descripcion}`;
  $("eventos").prepend(div);
  while ($("eventos").childElementCount > 150) $("eventos").lastChild.remove();
}

// ------------------------------------------------------------------ órdenes
async function enviar(ruta, metodo = "POST", cuerpo) {
  const r = await fetch(ruta, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  if (!r.ok) console.warn(ruta, await r.text());
}

function deslizador(id, salida, formato, alSoltar) {
  const el = $(id);
  el.addEventListener("input", () => { usuarioMoviendo = true; $(salida).textContent = formato(+el.value); });
  el.addEventListener("change", async () => { await alSoltar(+el.value); usuarioMoviendo = false; });
}

deslizador("sp", "spOut", (v) => `${v.toFixed(1)} m`, (v) => enviar("/api/setpoint", "POST", { valor: v }));
deslizador("ap", "apOut", (v) => `${Math.round(v)} %`, (v) => enviar("/api/valvula", "POST", { valor: v }));
deslizador("vm", "vmOut", (v) => `${Math.round(v)} %`, (v) => enviar("/api/modo", "POST", { modo: "manual", velocidad_manual: v }));
$("btnAuto").onclick = () => enviar("/api/modo", "POST", { modo: "auto" });
$("btnManual").onclick = () => enviar("/api/modo", "POST", { modo: "manual", velocidad_manual: +$("vm").value });
$("btnLimpiar").onclick = () => enviar("/api/fallas", "DELETE");
$("tablaAlarmas").addEventListener("click", (e) => {
  const tag = e.target.dataset?.tag;
  if (tag) enviar(`/api/alarmas/${tag}/reconocer`);
});
$("verReal").addEventListener("change", (e) => {
  verReal = e.target.checked;
  gNivel.data.datasets[2].hidden = !verReal;
  gNivel.update("none");
});

function pintarBotonesFalla(descripciones) {
  $("fallas").innerHTML = Object.entries(descripciones).map(([tipo, desc]) =>
    `<button class="falla" data-tipo="${tipo}">${NOMBRES_FALLA[tipo] ?? tipo}<small>${desc}</small></button>`).join("");
  document.querySelectorAll(".falla").forEach((b) => { b.onclick = () => enviar(`/api/fallas/${b.dataset.tipo}`); });
}

// ------------------------------------------------------------------ conexión
function conectar() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { $("conexion").classList.add("on"); $("conexionTxt").textContent = "en línea"; };
  ws.onclose = () => {
    $("conexion").classList.remove("on");
    $("conexionTxt").textContent = "reconectando…";
    setTimeout(conectar, 2000);
  };
  ws.onmessage = (msg) => {
    const d = JSON.parse(msg.data);
    if (d.tipo === "inicio") {
      [gNivel, gCaudal, gPuntaje].forEach((g) => { g.data.labels = []; g.data.datasets.forEach((s) => (s.data = [])); });
      d.historia.forEach(graficar);
      refrescarGraficas();
      $("eventos").innerHTML = "";
      d.eventos.forEach(agregarEvento);
      pintarBotonesFalla(d.fallas_disponibles);
      pintarAlarmas(d.alarmas);
      return;
    }
    const m = d.muestra;
    graficar(m);
    refrescarGraficas();
    pintarProceso(m);
    pintarDetector(m);
    pintarAlarmas(d.alarmas);
    d.eventos.forEach(agregarEvento);
  };
}
conectar();
