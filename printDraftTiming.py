import sys
import os
import argparse
from ast import literal_eval
import slack

def handleMissingChannelId(args, client):
	if(not args.channel_id):
		print("No channel ID specified.  Here are the available channels:")
		channel_list = client.channels_list()
		for channel in channel_list['channels']:
			print(channel['name'] + " -- " + channel['id'])
		exit()

def createUserAssociations(args, client):
	username_to_uid = {}
	uid_to_username = {}

	channel_info = client.channels_info(
  	channel=args.channel_id
	)

	for user in channel_info['channel']['members']:
		# if we were dealing with more users, could probably grab these as a batch but meh
		user_info = client.users_info(
  		user=user
		)
		username = user_info['user']['name']
		username_to_uid[username] = user
		uid_to_username[user] = username

	for name in args.draft_order:
		if not name in username_to_uid:
			print("Couldn't find slack user '%s', exiting" % name)
			exit()

	return username_to_uid, uid_to_username

def getTimeOrderedMessages(args, client):
	all_messages = []
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

		#print(str(conversations['ok']) + " -- " + str(conversations['has_more']) + " -- " + str(len(conversations['messages'])))

		all_messages.extend(conversations['messages'])

		if not conversations['has_more']:
			break

		all_messages.sort(key=(lambda message: message['ts']))
		return all_messages

def printMessages(messages):
	for message in messages:
			if(message and message['text']):
				print(message['user'] + " -- " + message['ts'] + " -- " + message['text'])

parser = argparse.ArgumentParser() 
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", nargs='+')
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)
username_to_uid, uid_to_username = createUserAssociations(args,client)
messages = getTimeOrderedMessages(args, client)
printMessages(messages)