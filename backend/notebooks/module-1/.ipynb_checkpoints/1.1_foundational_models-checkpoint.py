from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from dotenv import load_dotenv
from pprint import pprint

load_dotenv()

## model invoke
model = init_chat_model(model="qwen2.5:14b", model_provider="ollama")

response = model.invoke("What's the capital of the Moon?")

print('\nresponse.content:')
print(response.content)

pprint(response.response_metadata)

print('-----------------')
## change model providers
model = init_chat_model(model="ollama:gpt-oss:20b")

response = model.invoke("What's the capital of the Moon?")
print(response.content)
pprint(response.response_metadata)


## agent invoke
print('-----------------')
agent = create_agent(model=model)

response = agent.invoke(
    {"messages": [HumanMessage(content="What's the capital of the Moon?")]}
)
pprint(response)

print('-----------------')
for token, metadata in agent.stream(
    {"messages": [HumanMessage(content="Tell me all about Luna City, the capital of the Moon")]},
    stream_mode="messages"
):

    # token is a message chunk with token content
    # metadata contains which node produced the token
    
    if token.content:  # Check if there's actual content
        print(token.content, end="", flush=True)  # Print token