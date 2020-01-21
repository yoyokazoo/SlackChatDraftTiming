import sys
import os
import argparse
from ast import literal_eval
import slack

class User:
	def setTagFromUid(self, _uid):
		if _uid:
			self.tag = "<@%s>" % _uid
	def setName(self, _name):
		self.name = _name
	def setUid(self, _uid):
		self.uid = _uid
		self.setTagFromUid(_uid)

	def __init__(self, _name = None, _uid = None):
		self.setName(_name)
		self.setUid(_uid)

class Draft:
	def __init__(self, _users_in_draft_order):
		self.users_in_draft_order = _users_in_draft_order

		# to be removed once we have a draft class? or at least re-arranged? should a user's neighbors be stored on user?
		# probably not, since it'll change if the wheel changes, should be accessed through draft helper method
		next_player_slack_tags = []
		for uid_index in range(len(users_in_draft_order)):
			next_player_index = uid_index + 1
			prev_player_index = uid_index - 1
			if next_player_index == len(users_in_draft_order):
				next_player_index = 0
			if prev_player_index == -1:
				prev_player_index = len(users_in_draft_order) - 1

			next_player_dict = {}
			next_player_dict['next'] = users_in_draft_order[next_player_index]
			next_player_dict['prev'] = users_in_draft_order[prev_player_index]

			next_player_slack_tags.append(next_player_dict)

		self.next_player_slack_tags = next_player_slack_tags
		print(self.users_in_draft_order)
		print(self.next_player_slack_tags)

def handleMissingChannelId(args, client):
	if(not args.channel_id):
		print("No channel ID specified.  Here are the available channels:")
		channel_list = client.channels_list()
		for channel in channel_list['channels']:
			print(channel['name'] + " -- " + channel['id'])
		exit()

def createUsers(args, client):
	users_in_draft_order = []

	username_to_uid = {}

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

	for name in args.draft_order:
		if not name in username_to_uid:
			print("Couldn't find slack user '%s', exiting.\nAvailable usernames are: %s" % (name, username_to_uid.keys()))
			exit()
		users_in_draft_order.append(User(name, username_to_uid[name]))

	return users_in_draft_order

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

def replaceUidWithUsername(str_to_replace, user):
	return str_to_replace.replace(user.tag, "@%s" % user.name)

def getYoureUpNextMessages(args, client, draft, messages):
	users_in_draft_order = draft.users_in_draft_order
	next_player_slack_tags = draft.next_player_slack_tags
	#print(messages)
	current_draft_round = 1
	draft_direction = 1
	draft_key = 'next'
	current_drafter_index = 0
	most_recent_message_index = 0

	IGNORE_THESE_MESSAGES = ["has joined the channel", "set the channel topic"]

	for message_index in range(len(messages)):
		message = messages[message_index]

		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in message['text'])] 
		if ignore:
			continue

		#for tag_to_match in next_player_slack_tags[current_drafter_index][draft_key]:
		tag_to_match = next_player_slack_tags[current_drafter_index][draft_key].tag
		#print("Checking %s against %s" % (tag_to_match, message['text']))

		# is it OK if someone else tags the person that's up? or should we check that the message sender is the previous drafter?
		if tag_to_match in message['text']:
			# update next drafter and direction properly so we know it for re-scan if necessary
			prev_drafter_index = current_drafter_index
			prev_draft_round = current_draft_round

			current_drafter_index = current_drafter_index + draft_direction
			if (draft_direction == 1 and current_drafter_index == len(users_in_draft_order) - 1) or (draft_direction == -1 and current_drafter_index == 0):
				current_draft_round = current_draft_round + 1
				if current_draft_round % 2 == 0:
					draft_direction = -1
					draft_key = 'prev'
				else:
					draft_direction = 1
					draft_key = 'next'

			# check that there aren't a lot of legal tags in between the start and end index.  If so, we probably missed one and should do a re-scan
			# this might not work?? needs more testing
			inner_message_tag_count = 0
			for inner_message_index_offset in range(message_index - most_recent_message_index):
				inner_message_index = inner_message_index_offset + most_recent_message_index + 1
				#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
				inner_message = messages[inner_message_index]

				ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in inner_message['text'])] 
				if ignore:
					continue

				#print("Checking tags against %s" % (inner_message['text']))
				player_tagged = ignore = [user for user in users_in_draft_order if(user.uid in inner_message['text'])] 
				if player_tagged:
					inner_message_tag_count = inner_message_tag_count + 1
			if inner_message_tag_count > 5: # Needs re-scan.  5 chosen to avoid triggering on chatter in between but not guaranteeing the 8-9 that a miss would result in. len(draft_order)/2+1?
					# looks suspiscious, let's re-scan.  for example, player B needs to pick, then it will be player A's turn
					# search for player A's next tag, then look backwards for player B's most recent message.  That one is likely their actual draft.
					print("Inner message tag count = %d... worth re-searching? (YES!)" % inner_message_tag_count)

					rescan_tag_to_match = next_player_slack_tags[current_drafter_index][draft_key].tag

					for rescan_message_index_offset in range(message_index - most_recent_message_index):
						rescan_message_index = rescan_message_index_offset + most_recent_message_index + 1
						#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
						rescan_message = messages[rescan_message_index]

						ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in rescan_message['text'])] 
						if ignore:
							continue

						if rescan_tag_to_match in rescan_message['text']:
							print("Found what we think the next tag is: %s" % rescan_message['text'])
							next_player_rescan_index = rescan_message_index

							for reverse_message_index_offset in reversed(range(next_player_rescan_index - most_recent_message_index)):
								reverse_message_index = reverse_message_index_offset + most_recent_message_index
								#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
								reverse_message = messages[reverse_message_index]
								print("Checking for most recent message from against %s" % (reverse_message['text']))

								ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in reverse_message['text'])] 
								if ignore:
									continue

								if reverse_message['user'] == users_in_draft_order[prev_drafter_index].uid:
									print("Most recent message from %s is %s, assuming this is their pick." % (users_in_draft_order[prev_drafter_index].uid, reverse_message['text']))
									message_index = reverse_message_index
									break
						#print("Checking tags against %s" % (inner_message['text']))
						#player_tagged = ignore = [next_players_tag for uid_tagged in all_uid_tags if(uid_tagged in rescan_message['text'])] 
						#if player_tagged:
						#	next_player_rescan_index = rescan_message_index

			#print("%s %s %s", (messages[message_index-1]['text'], messages[message_index]['text'], messages[message_index+1]['text']))
			print("%s drafted at: %s (%s). Next drafter is: %s" % (users_in_draft_order[prev_drafter_index].name, message['ts'], replaceUidWithUsername(messages[message_index]['text'].replace("\n", " "), users_in_draft_order[prev_drafter_index]), users_in_draft_order[current_drafter_index].name))
			if prev_draft_round != current_draft_round:
				print("Done with round %s after %s's pick" % (prev_draft_round, users_in_draft_order[current_drafter_index].name))
			#print("New tag to match is %s (%s)" % (next_player_slack_tags[current_drafter_index][draft_key], replaceUidWithUsername(next_player_slack_tags[current_drafter_index][draft_key], next_player_slack_tags[current_drafter_index])))
			
			most_recent_message_index = message_index


parser = argparse.ArgumentParser() 
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", default=['ADD_DRAFTERS_HERE'], nargs='+')
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)

users_in_draft_order = createUsers(args,client)
draft = Draft(users_in_draft_order)
messages = getTimeOrderedMessages(args, client)

#printMessages(messages)
getYoureUpNextMessages(args, client, draft, messages)