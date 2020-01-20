import sys
import os
import argparse
from ast import literal_eval
import slack

parser = argparse.ArgumentParser() 
parser.add_argument('-token', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-channel_id', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

if(not args.channel_id):
		print("No channel ID specified.  Here are the available channels:")
		channel_list = client.channels_list()
		for channel in channel_list['channels']:
			print(channel['name'] + " -- " + channel['id'])
		exit()

conversations = None
while True:
	if not conversations:
		conversations = client.conversations_history(channel=args.channel_id)
	else:
		conversations = client.conversations_history(
	  	channel=args.channel_id,
	  	cursor=conversations['response_metadata']['next_cursor']
		)

	if not conversations['ok']:
		break

	print(str(conversations['ok']) + " -- " + str(conversations['has_more']) + " -- " + str(len(conversations['messages'])))

	if not conversations['has_more']:
		break