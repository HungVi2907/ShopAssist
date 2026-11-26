"""Reproducible regression with external network denied; Windows asyncio uses loopback."""
import os,socket,pytest
os.environ['API_DEFAULT_TOP_K']='5'
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
original_connect=socket.socket.connect
original_dns=socket.getaddrinfo
def connect(sock,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
  raise RuntimeError('Offline regression forbids external socket connections')
 return original_connect(sock,address)
def dns(host,*args,**kwargs):
 if host not in ('127.0.0.1','::1','localhost',None):
  raise RuntimeError('Offline regression forbids external DNS')
 return original_dns(host,*args,**kwargs)
socket.socket.connect=connect;socket.getaddrinfo=dns
args=['tests/test_llm_gateway_ollama_adapter.py','tests/test_phase18_5.py','tests/test_phase18_4.py','tests/test_api_orchestrator.py','tests/test_api_integration_mocked.py','tests/test_api_config_and_schemas.py','tests/test_api_price_adapter.py','tests/test_phase18_3.py','tests/test_phase18_2.py','tests/test_query_understanding.py','tests/test_preferences.py','tests/test_retrieval_text.py','tests/test_hybrid_retrieval.py','tests/test_reranking.py','tests/test_recommendation.py','tests/test_ollama_query_understanding.py','tests/test_phase8_refinement_rules.py','tests/test_phase8_schema_refinement.py','tests/test_phase18_lifecycle.py','tests/test_llm_gateway_schemas.py','tests/test_llm_gateway_config.py','tests/test_llm_gateway_registry.py','tests/test_llm_gateway_gateway.py','tests/test_llm_gateway_policies.py','tests/test_llm_gateway_health_quota.py','tests/test_llm_gateway_telemetry.py','tests/test_llm_gateway_gemini.py','tests/test_llm_gateway_chat_adapters.py','tests/test_bot_application.py','tests/test_bot_client.py','tests/test_bot_commands.py','tests/test_bot_config.py','tests/test_bot_formatters.py','tests/test_bot_integration_mocked.py','tests/test_bot_messages.py','tests/test_bot_sessions.py','-q']
raise SystemExit(pytest.main(args))
