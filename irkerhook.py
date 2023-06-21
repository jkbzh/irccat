#!/usr/bin/env python3
# Copyright (c) 2012 Eric S. Raymond <esr@thyrsus.com>
# SPDX-License-Identifier: BSD-2-Clause
'''
This script contains git porcelain and porcelain byproducts.
Requires either Python 2.6, or 2.5 with the simplejson library installed
or Python 3.x.

usage: irkerhook.py [-V] [-n] [--variable=value...] [commit_id...]

This script is meant to be run in an update or post-commit hook.
Try it with -n to see the notification dumped to stdout and verify
that it looks sane. With -V this script dumps its version and exits.

See the irkerhook manual page in the distribution for a detailed
explanation of how to configure this hook.

The default location of the irker proxy, if the project configuration
does not override it.
'''
# SPDX-License-Identifier: BSD-2-Clause
from __future__ import print_function, absolute_import

# pylint: disable=line-too-long,invalid-name,missing-function-docstring,missing-class-docstring,no-else-break,no-else-return,too-many-instance-attributes,too-many-locals,too-many-branches,too-many-statements,redefined-outer-name,import-outside-toplevel,raise-missing-from,consider-using-f-string,redundant-u-string-prefix,redundant-u-string-prefix,consider-using-with

default_server = "localhost"
IRKER_PORT = 6659

# The default service used to turn your web-view URL into a tinyurl so it
# will take up less space on the IRC notification line.
default_tinyifier = u"http://tinyurl.com/api-create.php?url="

# Map magic urlprefix values to actual URL prefixes.
urlprefixmap = {
    "viewcvs": "http://%(host)s/viewcvs/%(repo)s?view=revision&revision=",
    "gitweb": "http://%(host)s/cgi-bin/gitweb.cgi?p=%(repo)s;a=commit;h=",
    "cgit": "http://%(host)s/cgi-bin/cgit.cgi/%(repo)s/commit/?id=",
    }

# By default, ship to the freenode #commits list
default_channels = u"irc://chat.freenode.net/#commits"

#
# No user-serviceable parts below this line:
#

version = "2.21"

# pylint: disable=multiple-imports,wrong-import-position
import os, sys, socket, subprocess, locale, datetime, re

try:
    from shlex import quote as shellquote
except ImportError:
    from pipes import quote as shellquote

try:
    from urllib2 import urlopen, HTTPError
except ImportError:
    from urllib.error import HTTPError
    from urllib.request import urlopen

try:
    import simplejson as json	# Faster, also makes us Python-2.5-compatible
except ImportError:
    import json

if sys.version_info.major == 2:
    # pylint: disable=undefined-variable
    string_type = unicode
else:
    string_type = str

try:
    getstatusoutput = subprocess.getstatusoutput
except AttributeError:
    # pylint: disable=import-error
    import commands
    getstatusoutput = commands.getstatusoutput

def do(command):
    if sys.version_info.major == 2:
        return string_type(getstatusoutput(command)[1], locale.getlocale()[1] or 'UTF-8')
    else:
        return getstatusoutput(command)[1]

# pylint: disable=too-few-public-methods
class Commit:
    def __init__(self, extractor, commit):
        "Per-commit data."
        self.commit = commit
        self.branch = None
        self.rev = None
        self.mail = None
        self.author = None
        self.files = None
        self.logmsg = None
        self.url = None
        self.author_name = None
        self.author_date = None
        self.commit_date = None
        self.id = None
        self.__dict__.update(extractor.__dict__)

        if sys.version_info.major == 2:
            # Convert __str__ to __unicode__ for python 2
            self.__unicode__ = self.__str__
            # Not really needed, but maybe useful for debugging
            self.__str__ = lambda x: x.__unicode__().encode('utf-8')

    def __str__(self):
        "Produce a notification string from this commit."
        # pylint: disable=no-member
        if not self.urlprefix:
            self.url = ""
        else:
            # pylint: disable=no-member
            urlprefix = urlprefixmap.get(self.urlprefix, self.urlprefix)
            webview = (urlprefix % self.__dict__) + self.commit
            try:
                # See it the url is accessible
                res = urlopen(webview)
                if self.tinyifier and self.tinyifier.lower() != "none":
                    try:
                        # Didn't get a retrieval error on the web
                        # view, so try to tinyify a reference to it.
                        self.url = urlopen(self.tinyifier + webview).read()
                        try:
                            self.url = self.url.decode('UTF-8')
                        except UnicodeError:
                            pass
                    except IOError:
                        self.url = webview
                else:
                    self.url = webview
            except HTTPError as e:
                if e.code == 401:
                    # Authentication error, so we assume the view is valid
                    self.url = webview
                else:
                    self.url = ""
            except IOError:
                self.url = ""
        # pylint: disable=no-member
        res = self.template % self.__dict__
        return string_type(res, 'UTF-8') if not isinstance(res, string_type) else res

class GenericExtractor:
    "Generic class for encapsulating data from a VCS."
    booleans = ["tcp"]
    numerics = ["maxchannels"]
    strings = ["email"]
    def __init__(self, arguments):
        self.arguments = arguments
        self.project = None
        self.repo = None
        # These aren't really repo data but they belong here anyway...
        self.email = None
        self.tcp = True
        self.tinyifier = default_tinyifier
        self.server = None
        self.channels = None
        self.maxchannels = 0
        self.template = None
        self.urlprefix = None
        self.host = socket.getfqdn()
        self.cialike = None
        self.filtercmd = None
        # Color highlighting is disabled by default.
        self.color = None
        self.bold = self.green = self.blue = self.yellow = self.red = ""
        self.brown = self.magenta = self.cyan = self.reset = ""
    def activate_color(self, style):
        "IRC color codes."
        if style == 'mIRC':
            # mIRC colors are mapped as closely to the ANSI colors as
            # possible.  However, bright colors (green, blue, red,
            # yellow) have been made their dark counterparts since
            # ChatZilla does not properly darken mIRC colors in the
            # Light Motif color scheme.
            self.bold = '\x02'
            self.green = '\x0303'
            self.blue = '\x0302'
            self.red = '\x0304'
            self.red = '\x0305'
            self.yellow = '\x0307'
            self.brown = '\x0305'
            self.magenta = '\x0306'
            self.cyan = '\x0310'
            self.reset = '\x0F'
        if style == 'ANSI':
            self.bold = '\x1b[1m'
            self.green = '\x1b[1;32m'
            self.blue = '\x1b[1;34m'
            self.red = '\x1b[1;31m'
            self.yellow = '\x1b[1;33m'
            self.brown = '\x1b[33m'
            self.magenta = '\x1b[35m'
            self.cyan = '\x1b[36m'
            self.reset = '\x1b[0m'
    def load_preferences(self, conf):
        "Load preferences from a file in the repository root."
        if not os.path.exists(conf):
            return
        ln = 0
        with open(conf, encoding='ascii', errors='surrogateescape') as rfp:
            for line in rfp:
                ln += 1
                if line.startswith("#") or not line.strip():
                    continue
                if line.count('=') != 1:
                    sys.stderr.write('%s:%d: missing = in config line\n' \
                                     % (conf, ln))
                    continue
                fields = line.split('=')
                if len(fields) != 2:
                    sys.stderr.write('%s:%d: too many fields in config line\n' \
                                     % (conf, ln))
                    continue
                variable = fields[0].strip()
                value = fields[1].strip()
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                # User cannot set maxchannels - only a command-line arg can do that.
                if variable == "maxchannels":
                    return
                setattr(self, variable, value)
    def do_overrides(self):
        "Make command-line overrides possible."
        for tok in self.arguments:
            for key in self.__dict__:
                if tok.startswith("--" + key + "="):
                    val = tok[len(key)+3:]
                    setattr(self, key, val)
        for (key, val) in self.__dict__.items():
            if key in GenericExtractor.booleans:
                if isinstance(val, str) and val.lower() == "true":
                    setattr(self, key, True)
                elif isinstance(val, str) and val.lower() == "false":
                    setattr(self, key, False)
            elif key in GenericExtractor.numerics:
                setattr(self, key, int(val))
            elif key in GenericExtractor.strings:
                setattr(self, key, val)
        if not self.project:
            sys.stderr.write("irkerhook.py: no project name set!\n")
            raise SystemExit(1)
        if not self.repo:
            self.repo = self.project.lower()
        if not self.channels:
            self.channels = default_channels % self.__dict__
        if self.color and self.color.lower() != "none":
            self.activate_color(self.color)

def has(dirname, paths):
    "Test for existence of a list of paths."
    # all() is a python2.5 construct
    for exists in [os.path.exists(os.path.join(dirname, x)) for x in paths]:
        if not exists:
            return False
    return True

# VCS-dependent code begins here

class GitExtractor(GenericExtractor):
    "Metadata extraction for the git version control system."
    @staticmethod
    def is_repository(dirname):
        # Must detect both ordinary and bare repositories
        return has(dirname, [".git"]) or \
               has(dirname, ["HEAD", "refs", "objects"])
    def __init__(self, arguments):
        GenericExtractor.__init__(self, arguments)
        # Get all global config variables
        self.project = do("git config --get irker.project")
        self.repo = do("git config --get irker.repo")
        self.server = do("git config --get irker.server")
        self.channels = do("git config --get irker.channels")
        self.email = do("git config --get irker.email")
        self.tcp = do("git config --bool --get irker.tcp")
        self.template = do("git config --get irker.template") or u'%(bold)s%(project)s:%(reset)s %(green)s%(author)s%(reset)s %(repo)s:%(yellow)s%(branch)s%(reset)s * %(bold)s%(rev)s%(reset)s / %(bold)s%(files)s%(reset)s: %(logmsg)s %(brown)s%(url)s%(reset)s'
        self.tinyifier = do("git config --get irker.tinyifier") or default_tinyifier
        self.color = do("git config --get irker.color")
        self.urlprefix = do("git config --get irker.urlprefix") or u"gitweb"
        self.cialike = do("git config --get irker.cialike")
        self.filtercmd = do("git config --get irker.filtercmd")
        # These are git-specific
        self.refname = do("git symbolic-ref HEAD 2>/dev/null")
        self.revformat = do("git config --get irker.revformat")
        # The project variable defaults to the name of the repository toplevel.
        if not self.project:
            bare = do("git config --bool --get core.bare")
            if bare.lower() == "true":
                keyfile = "HEAD"
            else:
                keyfile = ".git/HEAD"
            here = os.getcwd()
            while True:
                if os.path.exists(os.path.join(here, keyfile)):
                    self.project = os.path.basename(here)
                    if self.project.endswith('.git'):
                        self.project = self.project[0:-4]
                    break
                elif here == '/':
                    sys.stderr.write("irkerhook.py: no git repo below root!\n")
                    sys.exit(1)
                here = os.path.dirname(here)
        # Get overrides
        self.do_overrides()
    # pylint: disable=no-self-use
    def head(self):
        "Return a symbolic reference to the tip commit of the current branch."
        return "HEAD"
    def commit_factory(self, commit_id):
        "Make a Commit object holding data for a specified commit ID."
        commit = Commit(self, commit_id)
        commit.branch = re.sub(r"^refs/[^/]*/", "", self.refname)
        # Compute a description for the revision
        if self.revformat == 'raw':
            commit.rev = commit.commit
        elif self.revformat == 'short':
            commit.rev = ''
        else: # self.revformat == 'describe'
            commit.rev = do("git describe %s 2>/dev/null" % shellquote(commit.commit))
        if not commit.rev:
            # Query git for the abbreviated hash
            commit.rev = do("git log -1 '--no-show-signature' '--pretty=format:%h' " + shellquote(commit.commit))
            if self.urlprefix in ('gitweb', 'cgit'):
                # Also truncate the commit used for the announced urls
                commit.commit = commit.rev
        # Extract the meta-information for the commit
        commit.files = do("git diff-tree -r --name-only " + shellquote(commit.commit))
        commit.files = " ".join(commit.files.strip().split("\n")[1:])
        # Design choice: for git we ship only the first message line, which is
        # conventionally supposed to be a summary of the commit.  Under
        # other VCSes a different choice may be appropriate.
        commit.author_name, commit.mail, commit.logmsg = \
            do("git log -1 '--no-show-signature' '--pretty=format:%an%n%ae%n%s' " + shellquote(commit.commit)).split("\n")
        # This discards the part of the author's address after @.
        # Might be be nice to ship the full email address, if not
        # for spammers' address harvesters - getting this wrong
        # would make the freenode #commits channel into harvester heaven.
        commit.author = commit.mail.split("@")[0]
        commit.author_date, commit.commit_date = \
            do("git log -1 '--no-show-signature' '--pretty=format:%ai|%ci' " + shellquote(commit.commit)).split("|")
        return commit

class SvnExtractor(GenericExtractor):
    "Metadata extraction for the svn version control system."
    @staticmethod
    def is_repository(dirname):
        return has(dirname, ["format", "hooks", "locks"])
    def __init__(self, arguments):
        GenericExtractor.__init__(self, arguments)
        # Some things we need to have before metadata queries will work
        self.repository = '.'
        for tok in arguments:
            if tok.startswith("--repository="):
                self.repository = tok[13:]
        self.project = os.path.basename(self.repository)
        self.template = '%(bold)s%(project)s%(reset)s: %(green)s%(author)s%(reset)s %(repo)s * %(bold)s%(rev)s%(reset)s / %(bold)s%(files)s%(reset)s: %(logmsg)s %(brown)s%(url)s%(reset)s'
        self.urlprefix = "viewcvs"
        self.id = None
        self.load_preferences(os.path.join(self.repository, "irker.conf"))
        self.do_overrides()
    # pylint: disable=no-self-use
    def head(self):
        sys.stderr.write("irker: under svn, hook requires a commit argument.\n")
        raise SystemExit(1)
    def commit_factory(self, commit_id):
        self.id = commit_id
        commit = Commit(self, commit_id)
        commit.branch = ""
        commit.rev = "r%s" % self.id
        commit.author = self.svnlook("author")
        commit.commit_date = self.svnlook("date").partition('(')[0]
        commit.files = self.svnlook("dirs-changed").strip().replace("\n", " ")
        commit.logmsg = self.svnlook("log").strip()
        return commit
    def svnlook(self, info):
        return do("svnlook %s %s --revision %s" % (shellquote(info), shellquote(self.repository), shellquote(self.id)))

class HgExtractor(GenericExtractor):
    "Metadata extraction for the Mercurial version control system."
    @staticmethod
    def is_repository(directory):
        return has(directory, [".hg"])
    def __init__(self, arguments):
        from mercurial.encoding import unifromlocal, unitolocal
        # This fiddling with arguments is necessary since the Mercurial hook can
        # be run in two different ways: either directly via Python (in which
        # case hg should be pointed to the hg_hook function below) or as a
        # script (in which case the normal __main__ block at the end of this
        # file is exercised).  In the first case, we already get repository and
        # ui objects from Mercurial, in the second case, we have to create them
        # from the root path.
        self.repository = None
        if arguments and isinstance(arguments[0], tuple):
            # Called from hg_hook function
            ui, self.repository = arguments[0]
            arguments = []  # Should not be processed further by do_overrides
        else:
            # Called from command line: create repo/ui objects
            from mercurial import hg, ui as uimod

            repopath = b'.'
            for tok in arguments:
                if tok.startswith('--repository='):
                    repopath = unitolocal(tok[13:])
            ui = uimod.ui()
            ui.readconfig(os.path.join(repopath, b'.hg', b'hgrc'), repopath)
            self.repository = hg.repository(ui, repopath)

        GenericExtractor.__init__(self, arguments)
        # Extract global values from the hg configuration file(s)
        self.project = unifromlocal(ui.config(b'irker', b'project') or b'')
        self.repo = unifromlocal(ui.config(b'irker', b'repo') or b'')
        self.server = unifromlocal(ui.config(b'irker', b'server') or b'')
        self.channels = unifromlocal(ui.config(b'irker', b'channels') or b'')
        self.email = unifromlocal(ui.config(b'irker', b'email') or b'')
        self.tcp = str(ui.configbool(b'irker', b'tcp'))  # converted to bool again in do_overrides
        self.template = unifromlocal(ui.config(b'irker', b'template') or b'')
        if not self.template:
            self.template = '%(bold)s%(project)s:%(reset)s %(green)s%(author)s%(reset)s %(repo)s:%(yellow)s%(branch)s%(reset)s * %(bold)s%(rev)s%(reset)s / %(bold)s%(files)s%(reset)s: %(logmsg)s %(brown)s%(url)s%(reset)s'
        self.tinyifier = unifromlocal(ui.config(
                b'irker', b'tinyifier',
                default=default_tinyifier.encode('utf-8')))
        self.color = unifromlocal(ui.config(b'irker', b'color') or b'')
        self.urlprefix = unifromlocal(ui.config(
                b'irker', b'urlprefix', default=ui.config(b'web', b'baseurl')))
        if self.urlprefix:
            # self.commit is appended to this by do_overrides
            self.urlprefix = (
                self.urlprefix.rstrip('/')
                + '/%s/rev/' % unifromlocal(self.repository.root).rstrip('/'))
        self.cialike = unifromlocal(ui.config(b'irker', b'cialike') or b'')
        self.filtercmd = unifromlocal(ui.config(b'irker', b'filtercmd') or b'')
        if not self.project:
            self.project = os.path.basename(unifromlocal(self.repository.root).rstrip('/'))
        self.do_overrides()
    # pylint: disable=no-self-use
    def head(self):
        "Return a symbolic reference to the tip commit of the current branch."
        return "-1"
    def commit_factory(self, commit_id):
        "Make a Commit object holding data for a specified commit ID."
        from mercurial.node import short
        from mercurial.templatefilters import person
        from mercurial.encoding import unifromlocal, unitolocal
        if isinstance(commit_id, str) and not isinstance(commit_id, bytes):
            commit_id = unitolocal(commit_id)
        ctx = self.repository[commit_id]
        commit = Commit(self, unifromlocal(short(ctx.hex())))
        # Extract commit-specific values from a "context" object
        commit.rev = '%d:%s' % (ctx.rev(), commit.commit)
        commit.branch = unifromlocal(ctx.branch())
        commit.author = unifromlocal(person(ctx.user()))
        commit.author_date = \
            datetime.datetime.fromtimestamp(ctx.date()[0]).strftime('%Y-%m-%d %H:%M:%S')
        commit.logmsg = unifromlocal(ctx.description())
        # Extract changed files from status against first parent
        st = self.repository.status(ctx.p1().node(), ctx.node())
        commit.files = unifromlocal(b' '.join(st.modified + st.added + st.removed))
        return commit

def hg_hook(ui, repo, **kwds):
    # To be called from a Mercurial "commit", "incoming" or "changegroup" hook.
    # Example configuration:
    # [hooks]
    # incoming.irker = python:/path/to/irkerhook.py:hg_hook
    extractor = HgExtractor([(ui, repo)])
    start = repo[kwds['node']].rev()
    end = len(repo)
    if start != end:
        # changegroup with multiple commits, so we generate a notification
        # for each one
        for rev in range(start, end):
            ship(extractor, rev, False)
    else:
        ship(extractor, kwds['node'], False)

# The files we use to identify a Subversion repo might occur as content
# in a git or hg repo, but the special subdirectories for those are more
# reliable indicators.  So test for Subversion last.
extractors = [GitExtractor, HgExtractor, SvnExtractor]

# VCS-dependent code ends here

def convert_message(message):
    """Convert the message to bytes to send to the socket"""
    return message.encode(locale.getlocale()[1] or 'UTF-8') + b'\n'

def ship(extractor, commit, debug):
    "Ship a notification for the specified commit."
    metadata = extractor.commit_factory(commit)

    # This is where we apply filtering
    if extractor.filtercmd:
        cmd = '%s %s' % (shellquote(extractor.filtercmd),
                          shellquote(json.dumps(metadata.__dict__)))
        data = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
        try:
            metadata.__dict__.update(json.loads(data))
        except ValueError:
            sys.stderr.write("irkerhook.py: could not decode JSON: %s\n" % data)
            raise SystemExit(1)

    # Rewrite the file list if too long. The objective here is only
    # to be easier on the eyes.
    if extractor.cialike \
           and extractor.cialike.lower() != "none" \
           and len(metadata.files) > int(extractor.cialike):
        files = metadata.files.split()
        dirs = {d.rpartition('/')[0] for d in files}
        if len(dirs) == 1:
            metadata.files = "(%s files)" % (len(files),)
        else:
            metadata.files = "(%s files in %s dirs)" % (len(files), len(dirs))
    # Message reduction.  The assumption here is that IRC can't handle
    # lines more than 510 characters long. If we exceed that length, we
    # try knocking out the file list, on the theory that for notification
    # purposes the commit text is more important.  If it's still too long
    # there's nothing much can be done other than ship it expecting the IRC
    # server to truncate.
    privmsg = string_type(metadata)
    if len(privmsg) > 510:
        metadata.files = ""
        privmsg = string_type(metadata)

    # Anti-spamming guard.  It's deliberate that we get maxchannels not from
    # the user-filtered metadata but from the extractor data - means repo
    # administrators can lock in that setting.
    channels = metadata.channels.split(",")
    if extractor.maxchannels != 0:
        channels = channels[:extractor.maxchannels]

    # Ready to ship.
    message = json.dumps({"to": channels, "privmsg": privmsg})
    if debug:
        print(message)
    elif channels:
        try:
            if extractor.email:
                # We can't really figure out what our SF username is without
                # exploring our environment. The mail pipeline doesn't care
                # about who sent the mail, other than being from sourceforge.
                # A better way might be to simply call mail(1)
                sender = "irker@users.sourceforge.net"
                msg = """From: %(sender)s
Subject: irker json

%(message)s""" % {"sender":sender, "message":message}
                import smtplib
                smtp = smtplib.SMTP()
                smtp.connect()
                smtp.sendmail(sender, extractor.email, msg)
                smtp.quit()
            elif extractor.tcp:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.connect((extractor.server or default_server, IRKER_PORT))
                    sock.sendall(convert_message(message))
                finally:
                    sock.close()
            else:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(convert_message(message), (extractor.server or default_server, IRKER_PORT))
                finally:
                    sock.close()
        except socket.error as e:
            sys.stderr.write("%s\n" % e)

if __name__ == "__main__":
    notify = True
    repository = os.getcwd()
    commits = []
    for arg in sys.argv[1:]:
        if arg == '-n':
            notify = False
        elif arg == '-V':
            print("irkerhook.py: version", version)
            sys.exit(0)
        elif arg.startswith("--repository="):
            repository = arg[13:]
        elif not arg.startswith("--"):
            commits.append(arg)

    # Figure out which extractor we should be using
    for candidate in extractors:
        if candidate.is_repository(repository):
            cls = candidate
            break
    else:
        sys.stderr.write("irkerhook: cannot identify a repository type.\n")
        raise SystemExit(1)
    extractor = cls(sys.argv[1:])

    # And apply it.
    if not commits:
        commits = [extractor.head()]
    for commit in commits:
        ship(extractor, commit, not notify)

# The following sets edit modes for GNU EMACS
# Local Variables:
# mode:python
# End:
