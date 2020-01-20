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

		next_player_dict = {}
		next_player_dict['next'] = ("<@%s>" % uid_draft_order[next_player_index])
		next_player_dict['prev'] = ("<@%s>" % uid_draft_order[prev_player_index])

		next_player_slack_tags.append(next_player_dict)
	print(uid_draft_order)
	print(next_player_slack_tags)

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

def replaceUidWithUsername(str_to_replace, uid_to_username):
	replaced_str = str_to_replace
	for k,v in uid_to_username.items():
		replaced_str = replaced_str.replace(k,v)
	return replaced_str

def getYoureUpNextMessages(args, client, messages, uid_to_username, uid_draft_order, next_player_slack_tags):
	#print(messages)
	current_draft_round = 1
	draft_direction = 1
	draft_key = 'next'
	current_drafter_index = 0
	most_recent_message_index = 0

	for message_index in range(len(messages)):
		message = messages[message_index]

		IGNORE_THESE_MESSAGES = ["has joined the channel", "set the channel topic"]
		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in message['text'])] 
		if ignore:
			continue

		#for tag_to_match in next_player_slack_tags[current_drafter_index][draft_key]:
		tag_to_match = next_player_slack_tags[current_drafter_index][draft_key]
		#print("Checking %s against %s" % (tag_to_match, message['text']))

		# is it OK if someone else tags the person that's up? or should we check that the message sender is the previous drafter?
		if tag_to_match in message['text']:
			#print("%s %s %s", (messages[message_index-1]['text'], messages[message_index]['text'], messages[message_index+1]['text']))
			prev_drafter_index = current_drafter_index
			prev_draft_round = current_draft_round

			current_drafter_index = current_drafter_index + draft_direction
			if (draft_direction == 1 and current_drafter_index == len(uid_draft_order) - 1) or (draft_direction == -1 and current_drafter_index == 0):
				current_draft_round = current_draft_round + 1
				if current_draft_round % 2 == 0:
					draft_direction = -1
					draft_key = 'prev'
				else:
					draft_direction = 1
					draft_key = 'next'

			print("%s drafted at: %s (%s). Next drafter is: %s" % (uid_to_username[uid_draft_order[prev_drafter_index]], message['ts'], replaceUidWithUsername(messages[message_index]['text'].replace("\n", " "), uid_to_username), uid_to_username[uid_draft_order[current_drafter_index]]))
			if prev_draft_round != current_draft_round:
				print("Done with round %s after %s's pick" % (prev_draft_round, uid_to_username[uid_draft_order[current_drafter_index]]))
			#print("New tag to match is %s (%s)" % (next_player_slack_tags[current_drafter_index][draft_key], replaceUidWithUsername(next_player_slack_tags[current_drafter_index][draft_key], uid_to_username)))
			# check that there aren't a lot of legal tags in between the start and end index.  If so, we probably missed one and should do a re-scan
			# this might not work?? needs more testing
			inner_message_tag_count = 0
			for inner_message_index_offset in range(message_index - most_recent_message_index):
				inner_message_index = inner_message_index_offset + most_recent_message_index + 1
				#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
				inner_message = messages[inner_message_index]
				inner_next_tag_to_match = next_player_slack_tags[current_drafter_index]['next']
				inner_prev_tag_to_match = next_player_slack_tags[current_drafter_index]['prev']
				#print("Checking %s and %s against %s" % (inner_next_tag_to_match, inner_prev_tag_to_match, inner_message['text']))
				if inner_next_tag_to_match in inner_message['text'] or inner_prev_tag_to_match in inner_message['text']:
					inner_message_tag_count = inner_message_tag_count + 1
			if inner_message_tag_count > 1:
					print("Inner message tag count = %d... worth re-searching? (YES!)" % inner_message_tag_count)
			most_recent_message_index = message_index


parser = argparse.ArgumentParser() 
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", default=['ADD_DRAFTERS_HERE'], nargs='+')
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)
username_to_uid, uid_to_username, uid_draft_order, next_player_slack_tags = createUserAssociations(args,client)
messages = getTimeOrderedMessages(args, client)
#printMessages(messages)
getYoureUpNextMessages(args, client, messages, uid_to_username, uid_draft_order, next_player_slack_tags)