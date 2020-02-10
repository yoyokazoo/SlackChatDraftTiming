import sys
import os
import argparse
from ast import literal_eval
import slack
import time
import json

noop = lambda *a, **k: None

IGNORE_THESE_MESSAGES = ["has joined the channel", "set the channel topic"]

def replaceUidWithUsername(str_to_replace, user):
	return str_to_replace.replace(user.tag, "@%s" % user.name)

def prettyPrint(draft, str):
	str = str.strip() # does this work?

	for drafter in draft.users_in_draft_order:
		str = replaceUidWithUsername(str, drafter)

	print(str)

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

	def __str__(self):
		return "%s (%s)" % (self.name, self.uid)
	def __repr__(self):
		return self.__str__()

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
	def getNextNextDrafter(self): # doesn't work on wheels... neither does getNextDrafter maybe?
		return self.users_in_draft_order[self.getSafeDrafterIndex(self.current_drafter_index + (self.draft_direction*2))]
	def changeDraftDirection(self):
		self.draft_direction = self.draft_direction * -1
	def getMiddleDraftRound(self):
		return (self.getDrafterCount() * 2)+1
	def isEarlyDraftRound(self):
		return self.current_draft_round < self.getMiddleDraftRound()
	def isMiddleDraftRound(self):
		return self.current_draft_round >= self.getMiddleDraftRound()
	def isUserOnFirstPickOfRound(self):
		# for this early round/middle round stuff, maybe we can use next_drafter_direction??
		early_round = self.draft_direction == 1 and self.current_drafter_index == self.start_drafter_index
		middle_round = self.draft_direction == -1 and self.current_drafter_index == self.start_drafter_index
		return (self.isEarlyDraftRound() and early_round) or (self.isMiddleDraftRound() and middle_round)
	def isUserOnMidRoundWheel(self):
		early_round = self.draft_direction == 1 and self.current_drafter_index == self.end_drafter_index
		middle_round = self.draft_direction == -1 and self.current_drafter_index == self.end_drafter_index
		return (self.isEarlyDraftRound() and early_round) or (self.isMiddleDraftRound() and middle_round)
	def isUserOnLastPickOfRound(self):
		early_round = self.draft_direction == -1 and self.current_drafter_index == self.start_drafter_index
		middle_round = self.draft_direction == 1 and self.current_drafter_index == self.start_drafter_index
		return (self.isEarlyDraftRound() and early_round) or (self.isMiddleDraftRound() and middle_round)
	def moveToNextDrafter(self):
		self.prev_drafter_index = self.current_drafter_index
		self.prev_draft_round = self.current_draft_round

		self.current_drafter_index = self.getSafeDrafterIndex(self.current_drafter_index + self.draft_direction)

		# modify this to respect starting_drafter_index to wheel properly
		if self.isUserOnMidRoundWheel():
			self.current_draft_round = self.current_draft_round + 1
			self.changeDraftDirection()
		elif self.isUserOnLastPickOfRound():
			self.current_draft_round = self.current_draft_round + 1
			# change to be extensible later on, since this draft is unusual
			if self.current_draft_round == 19:
				# full direction change, which end up keeping the same start drafter index and direction
				# just need to move end drafter index
				self.end_drafter_index = self.getSafeDrafterIndex(self.start_drafter_index + 1)
				self.next_drafter_direction = -1
			else:
				self.start_drafter_index = self.getSafeDrafterIndex(self.start_drafter_index + self.next_drafter_direction)
				self.end_drafter_index = self.getSafeDrafterIndex(self.end_drafter_index + self.next_drafter_direction)
				self.changeDraftDirection()

		#if draft.prev_draft_round != draft.current_draft_round:
		#		print("Done with round %s after %s's pick" % (draft.prev_draft_round, draft.getCurrentDrafter().name))

	def __init__(self, _users_in_draft_order):
		self.users_in_draft_order = _users_in_draft_order

		self.prev_draft_round = 1
		self.current_draft_round = 1

		self.draft_direction = 1
		self.next_drafter_direction = 1

		self.start_drafter_index = 0
		self.end_drafter_index = self.getDrafterCount() - 1

		self.prev_drafter_index = 0
		self.current_drafter_index = 0

		print(self.users_in_draft_order)

class Pick:
	raw_pick_index = 0

	def __init__(self, _user, _ts, _message, _round):
		self.user = _user
		self.ts = _ts
		self.message = _message
		self.round = _round
		self.pick_index = Pick.raw_pick_index
		Pick.raw_pick_index += 1

	def __str__(self):
		strtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.ts))
		return "(%s) %s picked at: %s (%s) (Round %s)" % (self.pick_index, self.user.name, strtime, self.message, self.round)
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

	channel_filename = args.channel_id + ".txt"
	if not os.path.isfile(channel_filename):
		f = open(channel_filename, "w+")
		f.close()

	with open(channel_filename, "r+", encoding="utf-8") as messages_file:
		
		slack_messages = []
		oldest_ts = 0

		messages_file_contents = messages_file.read()
		if messages_file_contents:
			slack_messages = json.loads(messages_file_contents)
			oldest_ts = slack_messages[-1]['ts']
			# timestamp is unique according to https://api.slack.com/events/message
			# so we don't have to worry about missing "simultaneous" messages

		conversations = None
		new_slack_messages = []
		while True:
			if not conversations:
				conversations = client.conversations_history(channel=args.channel_id, oldest=oldest_ts)
			else:
				conversations = client.conversations_history(
					channel=args.channel_id,
					cursor=conversations['response_metadata']['next_cursor']
				)

			if not conversations['ok']:
				break

			#print(str(conversations['ok']) + " -- " + str(conversations['has_more']) + " -- " + str(len(conversations['messages'])))

			new_slack_messages.extend(conversations['messages'])

			if not conversations['has_more']:
				break

		slack_messages.extend(new_slack_messages)
		slack_messages.sort(key=(lambda message: message['ts']))

		messages_file.seek(0)
		messages_file.write(json.dumps(slack_messages))
		messages_file.truncate()

	return slack_messages

def printMessages(messages):
	for message in messages:
			if(message and message['text']):
				print(message['user'] + " -- " + message['ts'] + " -- " + message['text'])

def getRescannedIndex(draft, messages, message_index, most_recent_message_index):
	rescan_tag_to_match = draft.getNextDrafter().tag
	prettyPrint(draft, "Tag we're trying to look for to resolve this: %s, current drafter uid: %s" % (rescan_tag_to_match, draft.getCurrentDrafter().uid)) if args.pick_index else noop()

	for rescan_message_index_offset in range(message_index - most_recent_message_index):
		rescan_message_index = rescan_message_index_offset + most_recent_message_index + 1
		#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
		rescan_message = messages[rescan_message_index]

		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in rescan_message['text'])]
		if ignore:
			continue

		if rescan_tag_to_match in rescan_message['text']:
			prettyPrint(draft, "Found what we think the next tag is: %s" % rescan_message['text']) if args.pick_index else noop()
			next_player_rescan_index = rescan_message_index

			for reverse_message_index_offset in reversed(range(next_player_rescan_index - most_recent_message_index)):
				reverse_message_index = reverse_message_index_offset + most_recent_message_index
				#print("%s %s %s" % (message_index, most_recent_message_index, inner_message_index))
				reverse_message = messages[reverse_message_index]
				prettyPrint(draft, "Checking for most recent message against %s (user: <@%s>)" % (reverse_message['text'], reverse_message['user'])) if args.pick_index else noop()

				ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in reverse_message['text'])]
				if ignore:
					continue

				rescan_drafter = draft.getCurrentDrafter()
				if draft.isUserOnFirstPickOfRound():
					rescan_drafter = draft.getPreviousDrafter()
				if reverse_message['user'] == rescan_drafter.uid:
					print("Most recent message from %s is %s, assuming this is their pick." % (rescan_drafter.name, reverse_message['text'])) if args.pick_index else noop()
					print("Setting message index to %d" % reverse_message_index) if args.pick_index else noop()
					return reverse_message_index

	return message_index

def getPicks(draft, messages):
	picks = []
	#print(messages)
	most_recent_message_index = 0

	# a little ugly fenceposting since we might modify the index on a rescan so a for loop won't work
	message_index = -1
	while message_index + 1 < len(messages):
		message_index = message_index + 1
		#print("Checking message index %d" % message_index)
		message = messages[message_index]

		ignore = [contains_ignore for contains_ignore in IGNORE_THESE_MESSAGES if(contains_ignore in message['text'])]
		if ignore:
			continue

		current_round = draft.current_draft_round
		previous_drafter = draft.getPreviousDrafter()
		current_drafter = draft.getCurrentDrafter()
		tag_to_match = draft.getNextDrafter().tag

		if args.pick_index and Pick.raw_pick_index == int(args.pick_index):
			prettyPrint(draft, "Checking %s against %s" % (tag_to_match, message['text']))
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
					prettyPrint(draft, "Inner message tag count = %d... worth re-searching? (YES!) Current drafter is %s" % (inner_message_tag_count, draft.getCurrentDrafter().name)) if args.pick_index else noop()
					message_index = getRescannedIndex(draft, messages, message_index, most_recent_message_index)

					
						#print("Checking tags against %s" % (inner_message['text']))
						#player_tagged = ignore = [next_players_tag for uid_tagged in all_uid_tags if(uid_tagged in rescan_message['text'])]
						#if player_tagged:
						#	next_player_rescan_index = rescan_message_index

			#print("%s %s %s", (messages[message_index-1]['text'], messages[message_index]['text'], messages[message_index+1]['text']))
			#print("%s drafted at: %s (%s). Next drafter is: %s" % (current_drafter.name, message['ts'], replaceUidWithUsername(messages[message_index]['text'].replace("\n", " "), current_drafter), draft.getCurrentDrafter().name))

			pick = Pick(current_drafter, int(float(message['ts'])), messages[message_index]['text'].replace("\n", " "), current_round)
			# print(str(pick) + " Next drafter is: %s" %  draft.getCurrentDrafter().name)
			picks.append(pick)

			most_recent_message_index = message_index

	return picks


parser = argparse.ArgumentParser()
parser.add_argument('-t', '--token', help="Workspace token of the app", required=True)
parser.add_argument('-c', '--channel_id', help="Channel ID of the channel you want to scan.  If not included, it will list the available channels and ids")
parser.add_argument('-d', '--draft_order', help="Order of drafters.  ", default=['ADD_DRAFTERS_HERE'], nargs='+')
parser.add_argument('-i', '--pick_index', help="If specified, output all text around this pick for debugging")
args = parser.parse_args()
print(args)

client = slack.WebClient(token=args.token)

handleMissingChannelId(args, client)

users_in_draft_order = createUsers(args,client)
messages = getTimeOrderedMessages(args, client)

draft = Draft(users_in_draft_order)
picks = getPicks(draft, messages)

if not args.pick_index:
	for pick in picks:
		prettyPrint(draft, pick.__str__())
#print(picks)

# TODO:
#Refactor message searching

#output picks to file, import picks from file, throw out dupes
# actually, put picks in the draft, export the draft, import the draft
# have the draft remember what message goes with last pick and pick up from there?
# we're going to lose slack history some day and want to be able to handle that

# output pick stats to file -- average time taken to pick, median, min, max

# specify file instead of token/channel/draft order, and store that inside draft

# back up file before creating a new one, since as development goes on I'll introduce bugs and corrupt things, and they'll be small enough

# be able to specify draft type? since this one is rather weird (esp. once we stop wheeling).  Inheritance structure?

# move classes to separate files (probably heavy-handed for this?)
