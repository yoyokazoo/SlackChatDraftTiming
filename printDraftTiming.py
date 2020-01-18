import sys
import os
import argparse
from ast import literal_eval
import slack

parser = argparse.ArgumentParser() 
parser.add_argument('-token', '--token', help="Slack token of the channel you want to scan", required=True)
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

print(client.channels_list())
print(client.conversations_list())

response = client.chat_postMessage(
    channel='CS0FCKUKA',
    text="Hello world!",
    user='U106198RM')
assert response["ok"]
assert response["message"]["text"] == "Hello world!"