// Pokémon RoleRun — interacción de la página.
//
// Los textos de los roles siguen lo que el programa aplica de verdad
// (app/role_rules.py y los grupos de data/moves.json), con la redacción de
// la Ayuda (app/role_content.py). Si cambia una regla, hay que cambiarla aquí.

const REPO = "dtimper/rolerun-manager";
const INSTALADOR = "RoleRunManager-Setup.exe";

const ROLES = [
  {
    clave: "libero", nombre: "Líbero", simbolo: "●",
    resumen: "El rol libre: no tiene restricciones propias de movimientos ni de objetos. Solo hay uno en el equipo.",
    permitido: "Movimientos de daño físico, movimientos de daño especial y cualquier movimiento de estado.",
    limites: "No tiene limitaciones propias del rol. Eso sí: si un movimiento se consiguió con un drafteo de otro rol, se avisa igual que cualquier otra incompatibilidad.",
  },
  {
    clave: "asesino", nombre: "Asesino", simbolo: "▲",
    resumen: "Atacante físico centrado en potenciar su Ataque y romper la Defensa rival.",
    permitido: "Movimientos de daño físico; boosts que aumenten al menos el Ataque; movimientos que reduzcan al menos la Defensa del rival; cualquier movimiento de estado que solo afecte a la Velocidad, o que suba Velocidad junto con Ataque (Danza Dragón, Cambio de Marcha); y Sustituto.",
    limites: "No puede usar movimientos de daño especial, boosts defensivos, movimientos que reduzcan los ataques del rival ni ningún otro movimiento de estado que no cumpla lo anterior.",
  },
  {
    clave: "mago", nombre: "Mago", simbolo: "■",
    resumen: "Atacante especial centrado en potenciar su Ataque Especial y romper la Defensa Especial rival.",
    permitido: "Movimientos de daño especial; boosts que aumenten al menos el Ataque Especial; movimientos que reduzcan al menos la Defensa Especial del rival; cualquier movimiento de estado que solo afecte a la Velocidad; y Sustituto.",
    limites: "No puede usar movimientos de daño físico, boosts defensivos, movimientos que reduzcan los ataques del rival ni otros movimientos de estado. Danza Aleteo y Geocontrol no valen: también suben la Defensa Especial, y esa combinación es de Prisma.",
  },
  {
    clave: "tanque", nombre: "Tanque", simbolo: "♥",
    resumen: "Defensor físico: puede atacar por cualquier lado, pero sus herramientas de estado deben reforzar la Defensa física.",
    permitido: "Movimientos de daño físico o especial que no recuperen PS; protecciones; Acua Aro, Arraigo y Drenadoras; movimientos que bajen el Ataque del rival (Gruñido, Encanto, Danza Pluma…), salvo que también bajen su Ataque Especial; boosts que aumenten la Defensa física sin aumentar la Defensa Especial (Corpulencia, Danza Triunfal…); y cualquier movimiento de estado que solo afecte a la Velocidad.",
    limites: "No puede recuperar PS con movimientos de daño ni con curación directa. Un boost que suba la Defensa Especial es ilegal aunque también suba la física: Masa Cósmica no vale. Del rival solo puede bajar el Ataque y la Velocidad: Rugido de Guerra u Ojos Llorosos, que bajan también el Ataque Especial, no valen.",
  },
  {
    clave: "prisma", nombre: "Prisma", simbolo: "★",
    resumen: "Defensor especial: puede atacar por cualquier lado, pero sus boosts deben incluir Defensa Especial sin aumentar la Defensa física.",
    permitido: "Movimientos de daño físico o especial que no recuperen PS; movimientos que provoquen un problema de estado, incluido envenenar sin dañar (Hilo Venenoso); Acua Aro, Arraigo y Drenadoras; movimientos que bajen el Ataque Especial del rival (Seducción, Onda Anómala, Confidencia), salvo que también bajen su Ataque; movimientos de estado que solo afecten a la Velocidad, o que la suban junto con la Defensa Especial (Danza Aleteo, Geocontrol); y boosts que suban la Defensa Especial sin subir la física (Paz Mental…).",
    limites: "No puede recuperar PS con movimientos de daño ni con curación directa. Cualquier boost que suba la Defensa física es ilegal, aunque también suba la Especial: Masa Cósmica no vale.",
  },
  {
    clave: "support", nombre: "Support", simbolo: "◆",
    resumen: "Rol de utilidad: estados, trampas de entrada, pantallas, curación y control del combate.",
    permitido: "Movimientos de utilidad, problemas de estado, trampas de entrada, pantallas y curación; movimientos que bajen cualquier estadística del rival, aunque sean varias (Trampa Venenosa); movimientos de estado que solo afecten a la Velocidad; y como máximo 2 movimientos de daño, físicos o especiales.",
    limites: "No puede usar movimientos de protección ni subir sus propias estadísticas, salvo la Velocidad. El ratio de crítico no cuenta, así que Foco Energía sí vale.",
  },
];

// ---------- Roles ----------
function pintarRoles() {
  const lista = document.getElementById("lista-roles");
  for (const rol of ROLES) {
    const tarjeta = document.createElement("button");
    tarjeta.type = "button";
    tarjeta.className = "rol aparece";
    tarjeta.style.setProperty("--c", `var(--${rol.clave})`);
    tarjeta.setAttribute("aria-expanded", "false");
    tarjeta.innerHTML = `
      <div class="rol-cabecera">
        <span class="rol-icono"><i style="--icono: url(assets/roles/${rol.clave}.png)"></i></span>
        <div><h3>${rol.nombre}</h3><span class="rol-simbolo">Marca ${rol.simbolo}</span></div>
      </div>
      <p class="rol-resumen">${rol.resumen}</p>
      <p class="rol-mas">Ver qué puede aprender →</p>
      <div class="rol-detalle">
        <div class="rol-caja si"><h4>Puede</h4><p>${rol.permitido}</p></div>
        <div class="rol-caja no"><h4>No puede</h4><p>${rol.limites}</p></div>
      </div>`;
    tarjeta.addEventListener("click", () => {
      const abierta = tarjeta.getAttribute("aria-expanded") === "true";
      for (const otra of lista.children) otra.setAttribute("aria-expanded", "false");
      if (!abierta) {
        tarjeta.setAttribute("aria-expanded", "true");
        tarjeta.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
    lista.appendChild(tarjeta);
  }
}

// ---------- Simulador de vidas ----------
const VIDAS_INICIALES = 10;
let vidas = VIDAS_INICIALES;

function pintarCorazones(animar = null) {
  const caja = document.getElementById("corazones");
  caja.innerHTML = "";
  const total = Math.max(vidas, VIDAS_INICIALES);
  for (let i = 0; i < total; i++) {
    const c = document.createElement("span");
    c.className = "corazon";
    c.textContent = "♥";
    if (i >= vidas) c.classList.add("roto");
    if (animar === "sube" && i === vidas - 1) c.classList.add("nuevo");
    caja.appendChild(c);
  }
  caja.setAttribute("aria-label", `${vidas} vidas`);
  document.getElementById("vidas-numero").textContent = vidas;
}

function combate(bajas) {
  if (vidas <= 0) return;
  const mensaje = document.getElementById("vidas-mensaje");
  if (bajas === 0) {
    vidas += 1;
    mensaje.textContent = "¡Sin bajas! +1 vida y un drafteo para tu equipo.";
    pintarCorazones("sube");
  } else {
    vidas = Math.max(0, vidas - bajas);
    mensaje.textContent = vidas === 0
      ? "0 vidas: la Run está perdida. Esos Pokémon se van al Cementerio para siempre."
      : `−${bajas} ${bajas === 1 ? "vida" : "vidas"}. Pero superaste el combate: te llevas un drafteo igualmente.`;
    pintarCorazones("baja");
  }
  for (const boton of document.querySelectorAll(".vidas-botones [data-bajas]")) boton.disabled = vidas === 0;
}

function prepararVidas() {
  pintarCorazones();
  for (const boton of document.querySelectorAll(".vidas-botones [data-bajas]")) {
    boton.addEventListener("click", () => combate(Number(boton.dataset.bajas)));
  }
  document.getElementById("vidas-reiniciar").addEventListener("click", () => {
    vidas = VIDAS_INICIALES;
    document.getElementById("vidas-mensaje").textContent = "Vuelta a empezar: 10 vidas.";
    for (const boton of document.querySelectorAll(".vidas-botones [data-bajas]")) boton.disabled = false;
    pintarCorazones();
  });
}

// ---------- Descarga: siempre la última versión publicada ----------
async function prepararDescarga() {
  const version = document.getElementById("descarga-version");
  const detalle = document.getElementById("descarga-detalle");
  const boton = document.getElementById("boton-descarga");
  try {
    const respuesta = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!respuesta.ok) throw new Error(respuesta.status);
    const release = await respuesta.json();
    const instalador = (release.assets || []).find((a) => a.name === INSTALADOR);
    const fecha = new Date(release.published_at).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
    version.textContent = `Versión ${release.tag_name.replace(/^v/, "")} · ${fecha}`;
    if (instalador) {
      boton.href = instalador.browser_download_url;
      const megas = Math.round(instalador.size / 1024 / 1024);
      detalle.textContent = `Windows 10 u 11 de 64 bits · ${megas} MB · Gratis`;
    } else {
      // Una versión sin instalador (solo pasa con las anteriores a la 0.5.0).
      boton.href = release.html_url;
      boton.textContent = "Ver la última versión";
    }
  } catch {
    // Sin conexión con GitHub, el enlace directo de siempre sigue valiendo.
  }
}

// ---------- Aparecer al hacer scroll ----------
function prepararApariciones() {
  const elementos = document.querySelectorAll(".aparece");
  if (!("IntersectionObserver" in window)) {
    elementos.forEach((e) => e.classList.add("visible"));
    return;
  }
  const observador = new IntersectionObserver((entradas) => {
    for (const entrada of entradas) {
      if (entrada.isIntersecting) {
        entrada.target.classList.add("visible");
        observador.unobserve(entrada.target);
      }
    }
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  elementos.forEach((e, i) => {
    e.style.transitionDelay = `${(i % 4) * 70}ms`;
    observador.observe(e);
  });
}

// ---------- Menú del móvil ----------
function prepararMenu() {
  const boton = document.querySelector(".menu-boton");
  const menu = document.getElementById("menu");
  boton.addEventListener("click", () => {
    const abierto = menu.classList.toggle("abierto");
    boton.setAttribute("aria-expanded", String(abierto));
  });
  menu.addEventListener("click", (evento) => {
    if (evento.target.tagName === "A") {
      menu.classList.remove("abierto");
      boton.setAttribute("aria-expanded", "false");
    }
  });
}

pintarRoles();
prepararVidas();
prepararMenu();
prepararApariciones();
prepararDescarga();
