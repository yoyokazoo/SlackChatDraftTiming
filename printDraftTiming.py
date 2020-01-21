import sys
import os
import argparse
from ast import literal_eval
import slack

def replaceUidWithUsername(str_to_replace, user):
	return str_to_replace.replace(user.tag, "@%s" % user.name)

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
	def getDrafterCount(self):
		return len(self.users_in_draft_order)
	def getSafeDrafterIndex(self, index):
		return index % self.getDrafterCount()
	def getCurrentDrafter(self):
		return self.users_in_draft_order[self.current_drafter_index]
	def getPreviousDrafter(self):
		return self.users_in_draft_order[self.getSafeDrafterIndex(self.current_drafter_index - self.draft_direction)]
	def getNextDrafter(self):
		return self.users_in_draft_order[self.getSafeDrafterIndex(self.current_drafter_index + self.draft_direction)]
	def changeDraftDirection(self):
		self.draft_direction = self.draft_direction * -1
	def moveToNextDrafter(self):
		self.prev_drafter_index = self.current_drafter_index
		self.prev_draft_round = self.current_draft_round

		self.current_drafter_index = self.getSafeDrafterIndex(self.current_drafter_index + self.draft_direction)

		# modify this to respect starting_drafter_index to wheel properly
		if self.draft_direction == 1 and self.current_drafter_index == self.end_drafter_index:
			self.changeDraftDirection()
		elif self.draft_direction == -1 and self.current_drafter_index == self.start_drafter_index:
			self.current_draft_round = self.current_draft_round + 1
			# change to be extensible later on, since this draft is unusual
			self.start_drafter_index = self.getSafeDrafterIndex(self.start_drafter_index + 1)
			self.end_drafter_index = self.getSafeDrafterIndex(self.end_drafter_index + 1)
			self.changeDraftDirection()

		#if draft.prev_draft_round != draft.current_draft_round:
		#		print("Done with round %s after %s's pick" % (draft.prev_draft_round, draft.getCurrentDrafter().name))

	def __init__(self, _users_in_draft_order):
		self.users_in_draft_order = _users_in_draft_order

		self.prev_draft_round = 1
		self.current_draft_round = 1
		
		self.draft_direction = 1

		self.start_drafter_index = 0
		self.end_drafter_index = self.getDrafterCount() - 1

		self.prev_drafter_index = 0
		self.current_drafter_index = 0

		print(self.users_in_draft_order)

class Pick:
	def __init__(self, _user, _ts, _message):
		self.user = _user
		self.ts = _ts
		self.message = _message

	def __str__(self):
		return "%s picked at: %s (%s)" % (self.user.name, self.ts, self.message)
	def __repr__(self):
		return self.__str__()

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

def getPicks(draft, messages):
	picks = []
	#print(messages)
	most_recent_message_index = 0

	IGNORE_THESE_MESSAGES = ["has joined the channel", "set the channel topic"]

	# a little ugly fenceposting since we might modify the index on a rescan so a for loop won't work
	message_index = -1
	while message_index + 1 < len(messages):
		message_index = message_index + 1
		#print("Checking message index %d" % message_index)
		message = messages[message_index]

		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in message['text'])] 
		if ignore:
			continue

		current_drafter = draft.getCurrentDrafter()
		tag_to_match = draft.getNextDrafter().tag
		#print("Checking %s against %s" % (tag_to_match, message['text']))

		# is it OK if someone else tags the person that's up? or should we check that the message sender is the previous drafter?
		if tag_to_match in message['text']:
			# update next drafter and direction properly so we know it for re-scan if necessary
			draft.moveToNextDrafter()

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
				player_tagged = [user for user in draft.users_in_draft_order if(user.uid in inner_message['text'])] 
				if player_tagged:
					inner_message_tag_count = inner_message_tag_count + 1
			if inner_message_tag_count > 5: # Needs re-scan.  5 chosen to avoid triggering on chatter in between but not guaranteeing the 8-9 that a miss would result in. len(draft_order)/2+1?
					# looks suspiscious, let's re-scan.  for example, player B needs to pick, then it will be player A's turn
					# search for player A's next tag, then look backwards for player B's most recent message.  That one is likely their actual draft.
					#print("Inner message tag count = %d... worth re-searching? (YES!) Current drafter is %s" % (inner_message_tag_count, draft.getCurrentDrafter().name))

					rescan_tag_to_match = draft.getNextDrafter().tag

					for rescan_message_index_offset in range(message_index - most_recent_message_index):
						rescan_message_index = rescan_message_index_offset + most_recent_message_index + 1
						#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
						rescan_message = messages[rescan_message_index]

						ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in rescan_message['text'])] 
						if ignore:
							continue

						if rescan_tag_to_match in rescan_message['text']:
							#print("Found what we think the next tag is: %s" % rescan_message['text'])
							next_player_rescan_index = rescan_message_index

							for reverse_message_index_offset in reversed(range(next_player_rescan_index - most_recent_message_index)):
								reverse_message_index = reverse_message_index_offset + most_recent_message_index
								#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
								reverse_message = messages[reverse_message_index]
								#print("Checking for most recent message against %s (user: %s)" % (reverse_message['text'], reverse_message['user']))

								ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in reverse_message['text'])] 
								if ignore:
									continue

								if reverse_message['user'] == current_drafter.uid:
									print("Most recent message from %s is %s, assuming this is their pick." % (current_drafter.name, reverse_message['text']))
									print("Setting message index to %d" % reverse_message_index)
									message_index = reverse_message_index
									break
						#print("Checking tags against %s" % (inner_message['text']))
						#player_tagged = ignore = [next_players_tag for uid_tagged in all_uid_tags if(uid_tagged in rescan_message['text'])] 
						#if player_tagged:
						#	next_player_rescan_index = rescan_message_index

			#print("%s %s %s", (messages[message_index-1]['text'], messages[message_index]['text'], messages[message_index+1]['text']))
			#print("%s drafted at: %s (%s). Next drafter is: %s" % (current_drafter.name, message['ts'], replaceUidWithUsername(messages[message_index]['text'].replace("\n", " "), current_drafter), draft.getCurrentDrafter().name))
			
			# need a "prettify" method that removes newlines, replaces UID tags with name tags, etc.
			pick = Pick(current_drafter, message['ts'], messages[message_index]['text'].replace("\n", " "))
			print(str(pick) + " Next drafter is: %s" %  draft.getCurrentDrafter().name)
			picks.append(pick)

			most_recent_message_index = message_index

	return picks


parser = argparse.ArgumentParser() 
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", default=['ADD_DRAFTERS_HERE'], nargs='+')
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)
users_in_draft_order = createUsers(args,client)
messages = getTimeOrderedMessages(args, client)

draft = Draft(users_in_draft_order)
picks = getPicks(draft, messages)

for pick in picks:
	print(pick)
#print(picks)