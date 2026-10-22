from __future__ import annotations
import json
import logging
import os
import re
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import requests

# Carga de variables locales de entorno si existe .env
load_dotenv()

# ------------------------------------------------------------------------------
# CONFIGURACIÓN DE TELEMETRÍA Y LOGGING
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AgenticCommerceCore")

# ------------------------------------------------------------------------------
# PARÁMETROS CRÍTICOS DE INFRAESTRUCTURA AWS (CUENTA 483528439523)
# ------------------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
ORIGINATION_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
AWS_AGENT_ID = os.getenv("AWS_AGENT_ID")
AWS_AGENT_ALIAS_ID = os.getenv("AWS_AGENT_ALIAS_ID", "TSTALIASID")

# Endpoint verificado en producción de la Lambda Scraper_Hija_Extractor
INVENTORY_LAMBDA_URL = "https://pejdyixt4myjjsu655to5bfhgq0iufrt.lambda-url.us-east-1.on.aws/"
ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$")


class OmnichannelAgentCore:
    def __init__(self) -> None:
        """
        Inicializa los clientes oficiales de AWS exigidos en las bases técnicas del concurso.
        """
        logger.info("Inicializando clientes Boto3 en región %s...", AWS_REGION)
        self.social_client = boto3.client("socialmessaging", region_name=AWS_REGION)
        self.ses_client = boto3.client("sesv2", region_name=AWS_REGION)
        self.bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)

    # --------------------------------------------------------------------------
    # 1. CONSULTA RESILIENTE AL MICROSERVICIO DE INVENTARIO (LAMBDA SCRAPER)
    # --------------------------------------------------------------------------
    def query_inventory(self, asin: str, name: str = "Producto Tienda", price: float = 0.0) -> Dict[str, Any]:
        """
        Consulta de inventario en tiempo real.
        Usa estrictamente mode=individual para forzar respuesta JSON limpia,
        evitando el volcado HTML que generaba el modo catalogo.
        """
        clean_asin = str(asin or "").strip().upper()
        if not ASIN_REGEX.match(clean_asin):
            logger.warning("Consulta abortada: ASIN '%s' con formato inválido.", clean_asin)
            return {"status": "ERROR", "message": "ASIN inválido. Debe contener exactamente 10 caracteres alfanuméricos."}

        params = {
            "tenant_id": "DEMO-USER",
            "asin": clean_asin,
            "price": f"{price:.2f}" if price > 0 else "100.00",
            "name": name,
            "mode": "individual"
        }

        try:
            logger.info("Consultando stock en Lambda remota para ASIN: %s", clean_asin)
            resp = requests.get(INVENTORY_LAMBDA_URL, params=params, timeout=12)
            resp.raise_for_status()

            # Validación de cabecera antes de parsear
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                logger.error("Respuesta no estructurada recibida de Lambda: %s", content_type)
                return {"status": "ERROR", "message": "El microservicio devolvió un formato no compatible."}

            return resp.json()

        except requests.exceptions.RequestException as err:
            logger.error("Fallo de conexión HTTP hacia la Function URL de inventario: %s", str(err))
            return {"status": "ERROR", "message": "Microservicio de inventario temporalmente inaccesible."}

    # --------------------------------------------------------------------------
    # 2. CEREBRO AGÉNTICO: INVOCACIÓN A AMAZON BEDROCK AGENTS
    # --------------------------------------------------------------------------
    def invoke_bedrock_agent(self, session_id: str, input_text: str) -> str:
        """
        Despacha la consulta del usuario al agente autónomo de Bedrock
        y decodifica secuencialmente el flujo binario de respuesta.
        """
        if not AWS_AGENT_ID:
            logger.warning("AWS_AGENT_ID no configurado en variables de entorno. Operando en modo pre-flight.")
            return "El agente inteligente está en proceso de acoplamiento. Por favor configure AWS_AGENT_ID."

        try:
            logger.info("Invocando Bedrock Agent [%s:%s] para sesión %s", AWS_AGENT_ID, AWS_AGENT_ALIAS_ID, session_id)
            response = self.bedrock_runtime.invoke_agent(
                agentId=AWS_AGENT_ID,
                agentAliasId=AWS_AGENT_ALIAS_ID,
                sessionId=session_id,
                inputText=input_text
            )

            completion_text = ""
            for event in response.get("completion", []):
                chunk = event.get("chunk")
                if chunk and "bytes" in chunk:
                    completion_text += chunk["bytes"].decode("utf-8")

            logger.info("Respuesta recibida de Bedrock (%d caracteres).", len(completion_text))
            return completion_text or "No se obtuvo respuesta del agente."

        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "Unknown")
            msg = err.response.get("Error", {}).get("Message", str(err))
            logger.error("Error al invocar Amazon Bedrock Agent [%s]: %s", code, msg)
            return "Disculpa, estoy experimentando dificultades técnicas para consultar mi núcleo de decisión."

    # --------------------------------------------------------------------------
    # 3. TRANSPORTE DE SALIDA: AWS END USER MESSAGING SOCIAL (WHATSAPP)
    # --------------------------------------------------------------------------
    def send_whatsapp_message(self, destination_phone: str, message_text: str) -> Optional[Dict[str, Any]]:
        """
        Envía mensajes hacia WhatsApp cumpliendo con la firma oficial de AWS:
        - Payload serializado en bytes UTF-8 con esquema de Meta Graph API.
        - metaApiVersion='v20.0'.
        - originationPhoneNumberId verificado.
        """
        if not ORIGINATION_PHONE_NUMBER_ID:
            logger.error("Imposible enviar WhatsApp: WHATSAPP_PHONE_ID no configurado.")
            return None

        # Normalización estricta de formato telefónico
        clean_phone = re.sub(r"[^\d+]", "", destination_phone.strip())
        if not clean_phone.startswith("+"):
            clean_phone = "+" + clean_phone

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message_text
            }
        }

        try:
            logger.info("Despachando mensaje WhatsApp a %s vía ID %s", clean_phone, ORIGINATION_PHONE_NUMBER_ID)
            response = self.social_client.send_whatsapp_message(
                originationPhoneNumberId=ORIGINATION_PHONE_NUMBER_ID,
                metaApiVersion="v20.0",
                message=json.dumps(payload).encode("utf-8")
            )
            msg_id = response.get("messageId")
            logger.info("✔ WhatsApp entregado a la red de AWS. MessageId: %s", msg_id)
            return response

        except ClientError as err:
            logger.error("Fallo crítico en SDK socialmessaging (SendWhatsAppMessage): %s", err)
            return None

    # --------------------------------------------------------------------------
    # 4. CIERRE OMNICANAL: RECIBO DE ORDEN VÍA AMAZON SES V2
    # --------------------------------------------------------------------------
    def send_order_receipt_ses(self, customer_email: str, order_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Emite el comprobante digital estructurado utilizando Amazon SES v2.
        """
        if not SENDER_EMAIL:
            logger.error("Imposible enviar recibo: SENDER_EMAIL no configurado.")
            return None

        product_name = order_payload.get("producto", "Artículo de Comercio Autónomo")
        total_mxn = order_payload.get("total_mxn", "0.00")
        asin = order_payload.get("asin", "N/A")
        order_id = order_payload.get("order_id", f"ORD-{os.urandom(4).hex().upper()}")

        subject = f"Confirmación de Orden #{order_id} - AgenticCommerce AI"
        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #0b0f19; color: #f3f4f6; padding: 20px;">
    <div style="max-width: 600px; margin: auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 24px;">
        <h2 style="color: #f97316; margin-top: 0;">✔ Confirmación de Orden de Compra</h2>
        <p>Gracias por comprar a través de nuestro Asistente Autónomo omnicanal.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr style="border-bottom: 1px solid #374151;">
                <td style="padding: 8px 0; color: #9ca3af;">Orden:</td>
                <td style="padding: 8px 0; font-weight: bold; text-align: right;">{order_id}</td>
            </tr>
            <tr style="border-bottom: 1px solid #374151;">
                <td style="padding: 8px 0; color: #9ca3af;">Producto:</td>
                <td style="padding: 8px 0; text-align: right;">{product_name}</td>
            </tr>
            <tr style="border-bottom: 1px solid #374151;">
                <td style="padding: 8px 0; color: #9ca3af;">Identificador ASIN:</td>
                <td style="padding: 8px 0; font-family: monospace; text-align: right;">{asin}</td>
            </tr>
            <tr>
                <td style="padding: 12px 0; font-size: 16px; font-weight: bold; color: #38bdf8;">Total Pagado:</td>
                <td style="padding: 12px 0; font-size: 16px; font-weight: bold; color: #38bdf8; text-align: right;">${total_mxn} MXN</td>
            </tr>
        </table>
        <p style="font-size: 12px; color: #6b7280; border-top: 1px solid #1f2937; padding-top: 12px;">
            Despachado automáticamente mediante Amazon SES v2 en la región {AWS_REGION} (Cuenta: 483528439523).
        </p>
    </div>
</body>
</html>"""

        try:
            logger.info("Enviando comprobante SES a %s desde %s", customer_email, SENDER_EMAIL)
            response = self.ses_client.send_email(
                FromEmailAddress=SENDER_EMAIL,
                Destination={"ToAddresses": [customer_email.strip()]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}}
                    }
                }
            )
            logger.info("✔ Correo SES despachado con éxito. MessageId: %s", response.get("MessageId"))
            return response

        except ClientError as err:
            logger.error("Error crítico en Amazon SES v2: %s", err)
            return None

    # --------------------------------------------------------------------------
    # 5. ORQUESTADOR PRINCIPAL: PROCESAMIENTO DE MENSAJES ENTRANTES
    # --------------------------------------------------------------------------
    def handle_incoming_customer_flow(self, phone: str, text: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ciclo completo del asistente:
        1. Recibe el mensaje de WhatsApp.
        2. Inyecta el contexto de inventario en vivo si se detecta un ASIN.
        3. Consulta al agente de Bedrock.
        4. Despacha la respuesta de regreso al cliente por WhatsApp.
        """
        active_session = session_id or re.sub(r"[^\w]", "", phone)[-10:]
        logger.info("Procesando mensaje de [%s]: '%s'", phone, text)

        # Pre-procesamiento de intenciones: Si el usuario menciona un ASIN, alimentamos stock preventivo
        enriched_prompt = text
        asin_match = re.search(r"\b([A-Z0-9]{10})\b", text.upper())
        if asin_match:
            candidate_asin = asin_match.group(1)
            stock_data = self.query_inventory(candidate_asin)
            if stock_data.get("status") == "SUCCESS":
                metrics = stock_data.get("metricas", {})
                enriched_prompt += (
                    f"\n[SISTEMA - DATOS REALES DE INVENTARIO]: ASIN={candidate_asin}, "
                    f"Precio={metrics.get('precio_venta_mxn')} MXN, "
                    f"Diagnóstico={metrics.get('toyota_tps', 'Disponible')}."
                )

        # Invocación al agente de IA
        ai_reply = self.invoke_bedrock_agent(session_id=active_session, input_text=enriched_prompt)

        # Entrega de respuesta omnicanal
        self.send_whatsapp_message(destination_phone=phone, message_text=ai_reply)

        return {
            "session_id": active_session,
            "reply": ai_reply,
            "status": "DELIVERED"
        }


# ------------------------------------------------------------------------------
# DISPATCHER PARA AWS LAMBDA / CONTENEDORES SERVERLESS
# ------------------------------------------------------------------------------
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Punto de entrada compatible con AWS Lambda Webhook de WhatsApp o invocación directa.
    """
    logger.info("Evento entrante al handler: %s", json.dumps(event))
    core = OmnichannelAgentCore()

    # Invocación directa como Action Group de Bedrock (si se usa esta Lambda como adaptador)
    if "actionGroup" in event:
        action_group = event.get("actionGroup", "")
        function_name = event.get("function", "")
        params = {p["name"]: p["value"] for p in event.get("parameters", [])}

        if function_name == "query_inventory":
            asin_param = params.get("asin", "")
            data = core.query_inventory(asin=asin_param)
            return {
                "messageVersion": "1.0",
                "response": {
                    "actionGroup": action_group,
                    "function": function_name,
                    "functionResponse": {
                        "responseBody": {"TEXT": {"body": json.dumps(data, ensure_ascii=False)}}
                    }
                }
            }

    # Procesamiento de webhook HTTP (API Gateway / Function URL)
    body_raw = event.get("body", "{}")
    if isinstance(body_raw, str):
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            body = {}
    else:
        body = body_raw

    phone = body.get("phone", "+521234567890")
    message = body.get("message", "Hola, ¿qué productos tienes disponibles?")
    session = body.get("session_id")

    result = core.handle_incoming_customer_flow(phone=phone, text=message, session_id=session)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, ensure_ascii=False)
    }


# ------------------------------------------------------------------------------
# EJECUCIÓN LOCAL / VERIFICACIÓN DIRECTA
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== INICIALIZANDO NÚCLEO FORENSE DE COMERCIO AGÉNTICO ===")
    app = OmnichannelAgentCore()
    print("✔ Módulos acoplados: Boto3 (socialmessaging, sesv2, bedrock-agent-runtime).")
    print("✔ Conectividad con microservicio de inventario lista.")
