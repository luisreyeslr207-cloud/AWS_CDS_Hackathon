import json
import os
import boto3
from botocore.exceptions import ClientError


class OmnichannelAgentBackend:
    def __init__(self):
        # Resolución dinámica de región con fallback canónico
        self.region = os.getenv('AWS_REGION', os.getenv('AWS_DEFAULT_REGION', 'us-east-1'))
        
        # Inicialización de clientes oficiales de AWS
        self.whatsapp_client = boto3.client('socialmessaging', region_name=self.region)
        self.ses_client = boto3.client('sesv2', region_name=self.region)
        self.bedrock_runtime = boto3.client('bedrock-agent-runtime', region_name=self.region)

    def process_customer_message(self, phone_number, message_text, session_id):
        """
        Paso 1: Recibe el mensaje de WhatsApp y consulta al Agente de Amazon Bedrock
        """
        print(f"[INPUT WHATSAPP] Mensaje de {phone_number}: {message_text}")

        agent_id = os.getenv('AWS_AGENT_ID')
        agent_alias_id = os.getenv('AWS_AGENT_ALIAS_ID')

        if not agent_id or not agent_alias_id:
            print("✖ Error de configuración: AWS_AGENT_ID o AWS_AGENT_ALIAS_ID no definidos.")
            return "Lo siento, el servicio de agente no está configurado correctamente."

        try:
            response = self.bedrock_runtime.invoke_agent(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
                inputText=message_text
            )

            completion = ""
            for event in response.get('completion', []):
                chunk = event.get('chunk')
                if chunk and 'bytes' in chunk:
                    completion += chunk['bytes'].decode('utf-8')

            print(f"[AGENT CORE] Respuesta inteligente generada: {completion}")
            return completion

        except ClientError as e:
            print(f"✖ Error al invocar Amazon Bedrock Agents: {e}")
            return "Lo siento, estoy experimentando problemas técnicos para procesar tu solicitud."

    def send_whatsapp_reply(self, destination_phone, text_content):
        """
        Paso 2: Envía la respuesta de la IA de vuelta a WhatsApp usando AWS End User Messaging Social
        """
        origination_phone_id = os.getenv('WHATSAPP_PHONE_ID')

        if not origination_phone_id:
            print("✖ Error de configuración: WHATSAPP_PHONE_ID no definido.")
            return None

        # Estructura de paquete oficial requerida por Meta WhatsApp Graph API
        whatsapp_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destination_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text_content
            }
        }

        try:
            # Serialización a bytes y envío con parámetros obligatorios de AWS
            response = self.whatsapp_client.send_whatsapp_message(
                originationPhoneNumberId=origination_phone_id,
                metaApiVersion='v20.0',
                message=json.dumps(whatsapp_payload).encode('utf-8')
            )
            print(f"✔ Mensaje de WhatsApp enviado con éxito. MessageId: {response.get('messageId')}")
            return response

        except ClientError as e:
            print(f"✖ Error crítico en SDK socialmessaging (SendWhatsAppMessage): {e}")
            return None

    def send_order_email_ses(self, customer_email, order_details):
        """
        Paso 3: Cierre omnicanal enviando el recibo de compra usando Amazon SES v2
        """
        sender_email = os.getenv('SENDER_EMAIL')

        if not sender_email:
            print("✖ Error de configuración: SENDER_EMAIL no definido.")
            return None

        try:
            response = self.ses_client.send_email(
                FromEmailAddress=sender_email,
                Destination={'ToAddresses': [customer_email]},
                Content={
                    'Simple': {
                        'Subject': {'Data': 'Confirmación de tu Pedido - Agente AI Store'},
                        'Body': {
                            'Text': {'Data': f"Gracias por tu compra.\n\nDetalles del pedido:\n{order_details}"}
                        }
                    }
                }
            )
            print(f"✔ Correo SES enviado correctamente. MessageId: {response.get('MessageId')}")
            return response

        except ClientError as e:
            print(f"✖ Error crítico en SDK sesv2 (SendEmail): {e}")
            return None


if __name__ == "__main__":
    print("--- INICIALIZANDO BACKEND DE AUDITORÍA AVANZADA ---")
    backend = OmnichannelAgentBackend()
    print("✔ Clientes de AWS CDS acoplados y listos para producción local.")
