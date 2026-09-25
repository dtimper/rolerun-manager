// Buzón de reportes de RoleRun Manager (Google Apps Script).
//
// Vive en la cuenta rolerunreports@gmail.com, implementado como "Aplicación
// web" (Ejecutar como: yo · Acceso: cualquier usuario). El programa le manda
// cada reporte por HTTPS y este script lo reenvía por correo a DESTINATARIO.
// Así el programa no lleva ninguna contraseña: su dirección solo sirve para
// mandar un reporte a DESTINATARIO, no para entrar en la cuenta ni para
// escribir a nadie más. Si alguien abusara de ella, basta con archivar la
// implementación en Google y publicar otra.

const DESTINATARIO = "timpertwitchtv@gmail.com";
const MAXIMO_POR_HORA = 30;
const MAXIMO_ADJUNTOS = 12;

function doPost(e) {
  try {
    const cache = CacheService.getScriptCache();
    const enviados = Number(cache.get("enviados") || 0);
    if (enviados >= MAXIMO_POR_HORA) {
      return responder({ ok: false, error: "limite" });
    }
    const datos = JSON.parse(e.postData.contents);
    const adjuntos = (datos.adjuntos || []).slice(0, MAXIMO_ADJUNTOS).map(function (a) {
      return Utilities.newBlob(Utilities.base64Decode(a.datos), a.tipo, a.nombre);
    });
    MailApp.sendEmail({
      to: DESTINATARIO,
      subject: String(datos.asunto || "[RoleRun] Reporte").slice(0, 200),
      body: String(datos.cuerpo || "").slice(0, 50000),
      attachments: adjuntos,
    });
    cache.put("enviados", String(enviados + 1), 3600);
    return responder({ ok: true });
  } catch (error) {
    return responder({ ok: false, error: String(error) });
  }
}

function doGet() {
  return responder({ ok: true, buzon: "RoleRun Manager" });
}

function responder(objeto) {
  return ContentService.createTextOutput(JSON.stringify(objeto))
    .setMimeType(ContentService.MimeType.JSON);
}
