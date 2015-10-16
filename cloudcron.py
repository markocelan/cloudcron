import cgi, endpoints
import urllib
import os, random, time, json
from datetime import datetime, timedelta


from google.appengine.ext import ndb
from google.appengine.api import users
from google.appengine.api import urlfetch

import webapp2
import jinja2

JINJA_ENVIRONMENT = jinja2.Environment(
	loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
	extensions=['jinja2.ext.autoescape'],
	autoescape=True)

class Project(ndb.Model):
	name = ndb.StringProperty()

class CronDefinition(ndb.Model):
	"""Models an individual Cron job definition."""
	name = ndb.StringProperty()
	period = ndb.IntegerProperty()
	ttl = ndb.IntegerProperty()
	url = ndb.StringProperty()

class CronJob(ndb.Model):
	"""Models an individual Cron job run."""
	starttime = ndb.DateTimeProperty(auto_now_add=True)
	status = ndb.StringProperty()
	output = ndb.TextProperty(default="")
	duration = ndb.IntegerProperty(default=-1)
	ttltimeout = ndb.DateTimeProperty()
	crondefinition = ndb.KeyProperty()

	status_class = ndb.ComputedProperty(lambda self: "info" if self.status == "running" else "success" if self.status == "success" else "danger")
	duration_str = ndb.ComputedProperty(lambda self: str("None") if self.starttime is None else str(datetime.utcnow() - self.starttime) if self.duration == -1 else str(timedelta(seconds=self.duration)))

class MainPage(webapp2.RequestHandler):
	def get(self):
		cronjobs = []
		crondefinitions = CronDefinition.query().fetch()
		for crondefinition in crondefinitions:
			cronjob = CronJob.query(CronJob.crondefinition == crondefinition.key).order(-CronJob.starttime).get()
			cronjobs.append((crondefinition, cronjob))

		template_values = {
			'cronjobs': cronjobs,
		}

		template = JINJA_ENVIRONMENT.get_template('index.html')
		self.response.write(template.render(template_values))

class EditCron(webapp2.RequestHandler):
	def get(self, cdid = None):
		crondefinition = None
		if cdid:
			crondefinition = ndb.Key(urlsafe=cdid).get()

		template_values = {
			'crondefinition': crondefinition,
		}

		template = JINJA_ENVIRONMENT.get_template('addcron.html')
		self.response.write(template.render(template_values))

	def post(self, cdid = None):
		if cdid:
			crondefinition = ndb.Key(urlsafe=cdid).get()
		else:
			crondefinition = CronDefinition()

		crondefinition.name=self.request.get('name')
		crondefinition.period=int(self.request.get('period'))
		crondefinition.ttl=int(self.request.get('ttl'))
		crondefinition.url=self.request.get('url')
		crondefinition.put()

		self.redirect('/')

class DeleteCron(webapp2.RequestHandler):
	def get(self, cdid):
		ndb.Key(urlsafe=cdid).delete()

		self.redirect('/')

class RunCron(webapp2.RequestHandler):
	def get(self):
		crons = CronDefinition.query().fetch()
		for cron in crons:
			timestamp = int(time.time())
			if (timestamp/60)%cron.period == 0:
				if CronJob.query(CronJob.status == "running", CronJob.crondefinition==cron.key).count() > 0:
					print("Already running.")
					continue
				cronjob = CronJob(status="running", crondefinition=cron.key, ttltimeout=datetime.utcnow() + timedelta(minutes=cron.ttl))
				cronjob.put()
				result = urlfetch.fetch(url=cron.url, headers={"X-Cloudcron-Callback": self.request.application_url + "/callback/" + cronjob.key.urlsafe()})
				if result.status_code != 200:
					cronjob.status = "failedtostart"
					cronjob.put()

		timedouts = CronJob.query(CronJob.status == "running", CronJob.ttltimeout <= datetime.utcnow()).fetch(100)
		for timedout in timedouts:
			print("Ttl timed out", timedout)
			timedout.status = "ttltimeout"
			timedout.put()

class ListCronJobs(webapp2.RequestHandler):
	def get(self, crondefinitionid):
		cdkey = ndb.Key(urlsafe=crondefinitionid)
		cronjobs = CronJob.query(CronJob.crondefinition == cdkey).order(-CronJob.starttime).fetch()

		template_values = {
			'cronjobs': cronjobs,
			'crondefinition': cdkey.get(),
		}

		template = JINJA_ENVIRONMENT.get_template('cronjoblist.html')
		self.response.write(template.render(template_values))

class CronCallback(webapp2.RequestHandler):
	def post(self, cronjobid):
		cronjob = ndb.Key(urlsafe=cronjobid).get()
		if cronjob.status != "running":
			self.response.status_int = 400
			return

		print self.request.body

		data = json.loads(self.request.body)
		if data["status"] == "success":
			status = "success"
		else:
			status = "failed"

		cronjob.duration = int((datetime.utcnow() - cronjob.starttime).total_seconds())
		cronjob.status = status
		cronjob.output = data.get("output", "")
		cronjob.put()

class CronJobDetail(webapp2.RequestHandler):
	def get(self, cronjobid):
		cronjob = ndb.Key(urlsafe=cronjobid).get()

		template_values = {
			'crondefinition': cronjob.crondefinition.get(),
			'cronjob': cronjob,
		}

		template = JINJA_ENVIRONMENT.get_template('cronjob.html')
		self.response.write(template.render(template_values))

class TestRun(webapp2.RequestHandler):
	def get(self):
		print(self.request.headers["X-Cloudcron-Callback"])
		a = int(self.request.get('ratio'))
		randomint = random.randrange(100)
		if randomint < a:
			self.response.status_int = 500

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/cron/add', EditCron),
    ('/cron/edit/(.+)', EditCron),
    ('/cron/delete/(.+)', DeleteCron),
    ('/cronjob/(.+)', CronJobDetail),
    ('/cron/run', RunCron),
    ('/cron/(.+)', ListCronJobs),
    ('/callback/(.+)', CronCallback),
    ('/testrun', TestRun),
])
