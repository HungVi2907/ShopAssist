"""Reproducible regression with external network denied; Windows asyncio uses loopback."""
import os,socket,pytest
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
args=['tests/test_phase18_2.py','tests/test_query_understanding.py','tests/test_preferences.py','tests/test_retrieval_text.py','tests/test_hybrid_retrieval.py','tests/test_reranking.py','tests/test_recommendation.py','tests/test_ollama_query_understanding.py','tests/test_phase8_refinement_rules.py','tests/test_phase8_schema_refinement.py','tests/test_phase18_lifecycle.py','-q']
raise SystemExit(pytest.main(args))
