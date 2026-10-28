from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from rich.pretty import pprint   #美化打印
#from rich import print  #覆盖print的美化打印

ollama_model = ChatOpenAI(
    model="qwen2.5:0.5b",
    api_key="ollama",  # 👈 Ollama 不校验 Key，但 ChatOpenAI 要求非空，占位即可
    base_url="http://localhost:11433/v1",  # http://ollama:11434/v1
)


agent=create_agent(
    model=ollama_model,
)

print(type(agent))   # langgraph底层的编译图对象
res=agent.invoke({"messages":[HumanMessage(content="hi")]},)
print(type(res))  #字典对象
pprint(res)  #输出res字典的美化打印，结构清晰
print(res["messages"][-1].content)
