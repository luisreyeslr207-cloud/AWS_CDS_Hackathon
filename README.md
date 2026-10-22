# 🛡️ Agentic AI Omnichannel Commerce Assistant

An autonomous, agent-driven conversational commerce solution built for the **AWS CDS Agentic AI Hackathon**. The system orchestrates conversational commerce through **WhatsApp** (powered by AWS End User Messaging Social), cognitive inventory reasoning via **Amazon Bedrock Agents** (Anthropic Claude 3.5 Sonnet), live real-time stock and margin auditing backed by **Amazon DynamoDB**, and automated transaction receipt dispatch using **Amazon SES v2**.

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer [Customer Touchpoint]
        A[Mobile Customer / WhatsApp]
    end

    subgraph MessagingLayer [AWS Ingestion & Transport]
        B[AWS End User Messaging Social]
        B -->|Meta Graph API v20.0| C[OmnichannelAgentCore / Webhook]
    end

    subgraph CognitiveLayer [Autonomous Intelligence]
        C -->|invoke_agent stream| D[Amazon Bedrock Agents]
        D -->|Foundation Model| E[Claude 3.5 Sonnet 20240620-v1:0]
        D -->|Action Group: InventoryManagement| F[Action Group Schema]
    end

    subgraph DataLayer [Live Serverless Data Engine]
        F -->|HTTPS / Function URL| G[AWS Lambda: Scraper_Hija_Extractor]
        G -->|Read / Write Partition| H[(Amazon DynamoDB: Historial_Precios)]
    end

    subgraph DispatchLayer [Post-Purchase Fulfilment]
        C -->|Transactional Dispatch| I[Amazon SES v2]
        I -->|HTML Digital Receipt| J[Customer Inbox]
    end

    A <--> B
    E --> D