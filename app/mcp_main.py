"""Entrada do conector MCP (independente do agente de WhatsApp: não usa nenhuma variável da Meta).

    uvicorn app.mcp_main:app --port 8000 --env-file .env
Endpoint do conector: /mcp  ·  saúde: /health

Produção: SUPABASE_URL + MCP_PUBLIC_URL (OAuth). Teste local: MCP_TOKEN + MCP_WA_ID.
"""
import logging
import os

from app import mcp_server

logging.basicConfig(level=logging.INFO)

if not os.environ.get("AGENTE_DB_URL", "").strip():
    raise RuntimeError("Variável de ambiente obrigatória vazia: AGENTE_DB_URL")

app = mcp_server.mcp.http_app(path="/mcp")
