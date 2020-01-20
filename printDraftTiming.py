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
			print("Couldn't find slack user '%s', exiting.\nAvailable usernames are: %s" % (name, username_to_uid.keys()))
			exit()

	uid_draft_order = []
	for username in args.draft_order:
		uid_draft_order.append(username_to_uid[username])
	# print(uid_draft_order)

	next_player_slack_tags = []
	for uid_index in range(len(uid_draft_order)):
		next_player_index = uid_index + 1
		prev_player_index = uid_index - 1
		if next_player_index == len(uid_draft_order):
			next_player_index = 0
		if prev_player_index == -1:
			prev_player_index = len(uid_draft_order) - 1

		next_player_array = []
		next_player_array.append("<@%s>" % uid_draft_order[next_player_index])
		next_player_array.append("<@%s>" % uid_draft_order[prev_player_index])

		next_player_slack_tags.append(next_player_array)
	# print(next_player_slack_tags)

	return username_to_uid, uid_to_username, uid_draft_order, next_player_slack_tags

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

		print(str(conversations['ok']) + " -- " + str(conversations['has_more']) + " -- " + str(len(conversations['messages'])))

		all_messages.extend(conversations['messages'])

		if not conversations['has_more']:
			break

		all_messages.sort(key=(lambda message: message['ts']))
	return all_messages

def printMessages(messages):
	for message in messages:
			if(message and message['text']):
				print(message['user'] + " -- " + message['ts'] + " -- " + message['text'])

def getYoureUpNextMessages(args, client, messages, uid_to_username, uid_draft_order, next_player_slack_tags):
	#print(messages)
	current_draft_round = 1
	current_drafter_index = 0
	most_recent_message_index = 0

	for message_index in range(len(messages)):
		message = messages[message_index]

		IGNORE_THESE_MESSAGES = ["has joined the channel", "set the channel topic"]
		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in message['text'])] 
		if ignore:
			continue

		for tag_to_match in next_player_slack_tags[current_drafter_index]:
			#print("Checking %s against %s" % (tag_to_match, message['text']))
			if tag_to_match in message['text']:
				print("%s drafted at: %s (%s)" % (uid_to_username[uid_draft_order[current_drafter_index]], message['ts'], messages[message_index]['text'].replace("\n", " ")))
				#print("%s %s %s", (messages[message_index-1]['text'], messages[message_index]['text'], messages[message_index+1]['text']))
				if current_drafter_index == len(uid_draft_order) - 1:
					print("Done with round %s" % current_draft_round)
					current_draft_round = current_draft_round + 1
					current_drafter_index = 0
				else:
					current_drafter_index = current_drafter_index + 1

				# check that there aren't a lot of legal tags in between the start and end index.  If so, we probably missed one and should do a re-scan
				for inner_message_index_offset in range(message_index - most_recent_message_index):
					inner_message_tag_count = 0
					inner_message_index = inner_message_index_offset + most_recent_message_index + 1
					#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
					inner_message = messages[inner_message_index]
					for tag_to_match in uid_draft_order:
						if tag_to_match in inner_message['text']:
							inner_message_tag_count = inner_message_tag_count + 1
					if inner_message_tag_count > 1:
						print("Inner message tag count = %d... worth re-searching?" % inner_message_tag_count)
				most_recent_message_index = message_index


parser = argparse.ArgumentParser() 
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", nargs='+')
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)
username_to_uid, uid_to_username, uid_draft_order, next_player_slack_tags = createUserAssociations(args,client)
messages = getTimeOrderedMessages(args, client)
#printMessages(messages)
getYoureUpNextMessages(args, client, messages, uid_to_username, uid_draft_order, next_player_slack_tags)