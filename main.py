#!/usr/bin/env python3

import http.client
import base64
import json
import re
from urllib.parse import urlencode, unquote # urlparse, parse_qs
from datetime import datetime, time, timezone, timedelta

#http://docs.tobesoft.com/advanced_development_guide_nexacro_17_ko#a5e1e2fb1080ae59
def nexacro_ssv_encode(info, enc="utf-8"):
  rs = '\x1e' # record separator
  return f"SSV:{enc}{rs}" + rs.join(f"{f}={v}" for (f,v) in info)

RE_H  = re.compile(b'SSV(:(?P<enc>utf-8|en_Us))?')
RE_DH = re.compile(b'Dataset:(?P<did>\w+)')
RE_V  = re.compile(b'(?P<vid>\w+)(:(?P<type>\w+)(\((?P<len>\d+)\))?)?(=(?P<val>.*))?', re.S)
RE_CC = re.compile(b'(?P<ccid>\w+)(:(?P<type>\w+)(\((?P<len>\d+)\))?)?(=(?P<val>.*))?', re.S)
RE_C  = re.compile(b'(?P<cid>\w+)(:(?P<type>\w+)(\((?P<len>\d+)\))?)?(:(?P<styp>\w+))?(:(?P<stxt>\w+))?')

def regmat(pattern, s, name):
  m = pattern.fullmatch(s)
  if m: return m
  raise ValueError(f"malformed {name}: '{s}'")

def nexacro_ssv_decode_dataset(vs, i):
  def checki():
    if len(vs) <= i: raise ValueError(f"imcomplete dataset at {i}'th record")

  m = regmat(RE_DH, vs[i], 'dataset header')
  did = m.group('did')
  i += 1

  checki()
  ccis = {}
  if vs[i][0:8] == b'_Const_\x1f':
    for s in vs[i].split(b'\x1f')[1:]:
      m = regmat(RE_CC, s, 'dataset const column info')
      ccis[m.group('ccid')] = m.group('val')
    i += 1

  checki()
  cis = []
  regmat(re.compile(b'^_RowType_\x1f'), vs[i][0:10], 'column infos')
  for s in vs[i].split(b'\x1f')[1:]:
    m = regmat(RE_C, s, 'dataset column info')
    cis.append(m.group('cid'))
  i += 1

  checki()
  rec = []
  while vs[i]:
    if vs[i][0] not in b'NIUDO' or vs[i][1:2] != b'\x1f':
      raise ValueError(f"malformed dataset row '{vs[i]}'")
    rec.append([None if x == b'\x03' else x for x in vs[i][2:].split(b'\x1f')])
    i += 1
    checki()

  i += 1
  return ((did, rec, ccis, cis), i)

def nexacro_ssv_decode(bs):
  vs = bs.split(b'\x1e')

  m = regmat(RE_H, vs[0], 'header')
  encoding = m.group('enc') or 'ascii'

  ret = {}
  i = 1
  while i < len(vs):
    if i == len(vs)-1 and vs[i] == b'': break
    elif vs[i][0:7] == b'Dataset':
      ((did, rec, ccis, cis), i) = nexacro_ssv_decode_dataset(vs, i)
      ret[did] = (rec, ccis, cis)
    else:
      m = regmat(RE_V, vs[i], 'variable')
      ret[m.group('vid')] = m.group('val')
      i += 1

  return ret


class ZeusRequest:

  # static vars
  TIME_ZONE = timezone(timedelta(hours=9))

  BASE_URL = "zeus.gist.ac.kr"

  LOGIN_PATH  = "/sys/login/auth.do?callback="
  ROLE_PATH   = "/sys/main/role.do"
  SELECT_PATH = "/amc/amcDailyTempRegE/select.do"
  SAVE_PATH   = "/amc/amcDailyTempRegE/save.do"

  SSV_GUBUN  = "AA"
  SSV_PGKEY  = "PERS07^PERS07_08^005^AmcDailyTempRegE"

  # copy & pasted from chrome inspector
  # then :s/^\([^:]\+\):\s*\(.\+\)$/"\1": '\2',/g
  # and removed some fields
  BASE_HEADERS = {
    "Host": BASE_URL,
    "Connection": 'keep-alive',
    "sec-ch-ua": '"Chromium";v="94", "Google Chrome";v="94", ";Not A Brand";v="99"',
    "Accept": 'application/json, text/javascript, */*; q=0.01',
    "Content-Type": 'application/x-www-form-urlencoded; charset=UTF-8',
    "X-Requested-With": 'XMLHttpRequest',
    "sec-ch-ua-mobile": '?0',
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36',
    "sec-ch-ua-platform": '"Windows"',
    "Origin": 'https://' + BASE_URL,
    "Sec-Fetch-Site": 'same-origin',
    "Sec-Fetch-Mode": 'cors',
    "Sec-Fetch-Dest": 'empty',
    "Accept-Encoding": 'gzip, deflate, br',
    "Accept-Language": 'ko-KR,ko;q=0.9',
  }

  def __init__(self, cache={}):
    self.conn = http.client.HTTPSConnection(self.BASE_URL);
    self.cookies = cache.get('cookies', {})
    cache.pop('cookies', None)
    self.cache = cache
    self.last_response = None
    self.last_data = None

  def get_cache(self):
    cache = self.cache.copy()
    cache['cookies'] = self.cookies
    return cache

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    self.conn.close()


  def cookie_monster(self, headers):
    for cookie in (hv for (hf,hv) in headers if hf == "Set-Cookie"):
      cookie_content = cookie.split(';')[0]
      (cf,cv) = cookie_content.split('=', 1)
      self.cookies[cf.strip()] = cv.strip()

  def cookie_demon(self):
    return "; ".join(f"{cf}={cv}" for (cf,cv) in self.cookies.items())


  def request_login(self, user_id, user_pw):
    params = urlencode({
      'login_id': user_id, 'login_pw': user_pw
    }, safe='!*()')
    headers = self.BASE_HEADERS.copy()
    headers["Cookie"] = self.cookie_demon()
    headers["Referer"] = 'https://' + self.BASE_URL + '/sys/main/login.do'

    self.conn.request("POST", self.LOGIN_PATH, params, headers)
    response = self.conn.getresponse()
    head = response.getheaders()
    self.cookie_monster(head)
    data = response.read()
    self.last_response = response
    self.last_data = data

    if response.status != 200:
      raise ConnectionError(
        f"server returned {response.status}, {response.reason}")

    try:
      dat = json.loads(unquote(data.decode("utf-8")))
      assert(not dat.get('error_msg', ''))
    except AssertionError:
      raise ConnectionError(dat['error_msg'])
    except e:
      raise ValueError(f"error while parsing data '{data}'")

    if 'WMONID' not in self.cookies or 'ZSESSIONID' not in self.cookies:
      raise ConnectionError(f"login successfully failed. '{head}'")


  def request_role(self):
    if 'WMONID' not in self.cookies:
      raise ConnectionRefusedError # need log-in

    info = [
      ('WMONID',    self.cookies['WMONID']),
      ('pg_key',    ""),
      ('pg_nm',     ""),
      ('page_open_time', ""),
      ('page_open_time_on', ""),
    ]

    params = nexacro_ssv_encode(info)
    headers = self.BASE_HEADERS.copy()
    headers["Referer"] = 'https://' + self.BASE_URL + '/index.html'
    headers["Accept"] = "*/*"
    headers["Content-Type"] = "text/plain;charset=UTF-8"
    headers["Cookie"] = self.cookie_demon()
    headers.pop("X-Requested-With", None)

    self.conn.request("POST", self.ROLE_PATH, params, headers)
    response = self.conn.getresponse()
    head = response.getheaders()
    self.cookie_monster(head)
    data = response.read()
    self.last_response = response
    self.last_data = data

    if response.status != 200:
      raise ConnectionError(
        f"server returned {response.status}, {response.reason}")

    ret = nexacro_ssv_decode(data)

    if b'ErrorMsg' in ret:
      if ret.get(b'ErrorCode', "") == b'4000':
        raise ConnectionRefusedError # re-login needed
      raise ConnectionError(ret[b'ErrorMsg'])

    if b'dsUserRole' not in ret:
      raise ValueError(f"expecting 'dsUserRole' got '{ret}'")

    (recs, ccid, cid) = ret[b'dsUserRole']

    try:
      dcd = cid.index(b'BASE_DEPT_CD')
      mbr = cid.index(b'MBR_NO')
    except ValueError:
      raise ValueError(f"role.do dataset fields inconsistent cid='{cid}' ccid='{ccid}'")

    return (recs[0][dcd].decode('utf-8'), recs[0][mbr].decode('utf-8'))


  def request_select(self):
    if 'WMONID' not in self.cookies:
      raise ConnectionRefusedError # need log-in
    if 'deptcd' not in self.cache:
      raise ConnectionRefusedError

    info = [
      ('WMONID',    self.cookies['WMONID']),
      ('dept_cd',   self.cache['deptcd']),
      ('chk_dt',    datetime.now(self.TIME_ZONE).strftime('%Y%m')),
      ('pg_key',    self.SSV_PGKEY),
      ('page_open_time', ""),
      ('page_open_time_on', datetime.now(self.TIME_ZONE).strftime('%Y%m%d%H%M%S%f')),
    ]

    params = nexacro_ssv_encode(info)
    headers = self.BASE_HEADERS.copy()
    headers["Referer"] = 'https://' + self.BASE_URL + '/index.html'
    headers["Accept"] = "*/*"
    headers["Content-Type"] = "text/plain;charset=UTF-8"
    headers["Cookie"] = self.cookie_demon()
    headers.pop("X-Requested-With", None)

    self.conn.request("POST", self.SELECT_PATH, params, headers)
    response = self.conn.getresponse()
    head = response.getheaders()
    self.cookie_monster(head)
    data = response.read()
    self.last_response = response
    self.last_data = data

    if response.status != 200:
      raise ConnectionError(
        f"server returned {response.status}, {response.reason}")

    ret = nexacro_ssv_decode(data)

    if b'ErrorMsg' in ret:
      if ret.get(b'ErrorCode', "") == b'4000':
        raise ConnectionRefusedError # re-login needed
      raise ConnectionError(ret[b'ErrorMsg'])

    if b'dsMain' not in ret:
      raise ValueError(f"expecting 'dsMain' got '{ret}'")

    dept = 0; name = 1; stdno = 2; date = 3;
    time = 4; temp = 5; sympt = 6;
    spc_ctnt = 12; gubun = 13 #? = 14
    recs = list(map(lambda row: {
      'timestamp': datetime.strptime(row[date]+row[time], '%Y%m%d%H:%M').replace(tzinfo=self.TIME_ZONE),
      'temperature': float(row[temp]),
      'symptoms': "".join("O" if x else "_" for x in row[sympt:sympt+6]),
      'significance': row[spc_ctnt]
      }, map(lambda row: [v.decode("utf-8") for v in row], ret[b'dsMain'][0])))
    return recs


  def request_save(self, symp={'temp':36.5}):
    if 'WMONID' not in self.cookies:
      raise ConnectionRefusedError # need log-in
    if 'deptcd' not in self.cache or 'mbrno' not in self.cache:
      raise ConnectionRefusedError

    info = [
      ('WMONID',    self.cookies['WMONID']),
      ('dept_cd',   self.cache['deptcd']),
      ('mbr_no',    self.cache['mbrno']),
      ('chk_dt',    datetime.now(self.TIME_ZONE).strftime('%Y-%m-%d')),
      ('temp',      f"{symp['temp']:.1f}"), # TODO catch error
      ('sympt_1',   'Y' if symp.get('cough', False) else 'N'),
      ('sympt_2',   'Y' if symp.get('soret', False) else 'N'),
      ('sympt_3',   'Y' if symp.get('dyspn', False) else 'N'),
      ('sympt_4',   'Y' if symp.get('fever', False) else 'N'),
      ('sympt_5',   'Y' if symp.get('losat', False) else 'N'),
      ('sympt_6',   'Y' if symp.get('orsym', False) else 'N'),
      ('spc_ctnt',  symp.get('special', "")),
      ('gubun',     self.SSV_GUBUN),
      ('pg_key',    self.SSV_PGKEY),
      ('page_open_time', ""),
      ('page_open_time_on', datetime.now(self.TIME_ZONE).strftime('%Y%m%d%H%M%S%f')),
    ]

    params = nexacro_ssv_encode(info)
    headers = self.BASE_HEADERS.copy()
    headers["Referer"] = 'https://' + self.BASE_URL + '/index.html'
    headers["Accept"] = "*/*"
    headers["Content-Type"] = "text/plain;charset=UTF-8"
    headers["Cookie"] = self.cookie_demon()
    headers.pop("X-Requested-With", None)

    self.conn.request("POST", self.SAVE_PATH, params, headers)
    response = self.conn.getresponse()
    head = response.getheaders()
    self.cookie_monster(head)
    data = response.read()

    if response.status != 200:
      raise ConnectionError(
        f"server returned {response.status}, {response.reason}")

    ret = nexacro_ssv_decode(data)

    if b'ErrorMsg' in ret:
      if ret.get(b'ErrorCode', "") == b'4000':
        raise ConnectionRefusedError # re-login needed
      raise ConnectionError(ret[b'ErrorMsg'])

    return ret

def show_record(rec):
  s_date = rec['timestamp'].strftime('%Y-%m-%d')
  s_time = rec['timestamp'].strftime('%H:%M')
  return "\t".join([
    s_date, s_time, str(rec['temperature']),
    rec['symptoms'], rec['significance']
  ])

def routine_args(argv):
  if len(argv) <= 1:
    print("Need a command to be specified.", file=sys.stderr)
    print("Use 'help' command to see usage.", file=sys.stderr)
    exit(1)

  cmd = argv[1]

  if len(argv) <= 2:
    config_path = DEFAULT_CONFIG_PATH
  else:
    config_path = argv[2]

  return (cmd, config_path)

def load_config(path):
  with open(path, "rt") as f:
    config_loaded = json.load(f)

  config = {}

  for (k,v) in CONFIG_SCHEME.items():
    if isinstance(v, type):
      # default value is not present, required field
      value_type = v
      if k not in config_loaded:
        raise ValueError(f"field '{k}' is required but missing")
      value = config_loaded.pop(k, None)
    else:
      # default value is present, optional field
      value_type = type(v)
      value = config_loaded.pop(k, v)

    if not isinstance(value, value_type):
      raise ValueError(f"field '{k}' should be of type {value_type.__name__} but is {value.__class__.__name__}")

    config[k] = value

  if config_loaded: # config_loaded \notin CONFIG_SCHEME
    entry = 'entry' if len(config_loaded) == 1 else 'entries'
    es = ', '.join(f"'{e}'" for e in config_loaded)
    raise ValueError(f"unrecognized config {entry}: {es}")

  #return (config, config_loaded)
  return config # TODO should this function return resting (unrecognized) entries to the caller insted of hadling it by itself?


def routine_load_config(path):
  try:
    return load_config(path)
  except (json.decoder.JSONDecodeError, ValueError) as e:
    print(f"Error while reading config: {e}.", file=sys.stderr)
    exit(3)
  except OSError as e:
    print(f"Error while reading config file at {path}.", file=sys.stderr)
    print(e, file=sys.stderr)
    exit(3)

def routine_load_cache(path):
  try:
    with open(path, "rt") as f:
      return json.load(f)
  except (FileNotFoundError, json.decoder.JSONDecodeError):
    return {} # especially when path == ''; indicating no cache store
  except OSError as e:
    print(f"Error while reading cache file '{path}'.", file=sys.stderr)
    print(e, file=sys.stderr)
    return {}

def routine_store_cache(cache, config):
  try:
    with open(config['cache_path'], "wt") as f:
      json.dump(cache, f, indent=2)
  except FileNotFoundError as e:
    return # especially when path == ''; indicating no cache store
  except OSError as e:
    print(f"Error while writing to cache file '{path}'.", file=sys.stderr)
    print(e, file=sys.stderr)

def routine_login(zrq, config):
  if config['verbose']: print("try loging in... ", end='', flush=True)
  try:
    password = base64.b64decode(config['b64_password'].encode('utf-8'))
    ret = zrq.request_login(config['username'], password)
  except ConnectionError as e:
    if config['verbose']: print("failed")
    print(e, file=sys.stderr)
    exit(4)
  if config['verbose']: print("success")

def routine_role(zrq, config):
  if config['verbose']: print("getting role data ... ", end='', flush=True)
  try:
    (deptcd, mbrno) = zrq.request_role()
  except ConnectionError as e:
    if config['verbose']: print("failed")
    print(e, file=sys.stderr)
    exit(4)
  if config['verbose']: print("success")

  zrq.cache['deptcd'] = deptcd
  zrq.cache['mbrno'] = mbrno

def execute_command(zrq, config, cmd, ret=False):
  if cmd == "save":
    if config['verbose']: print("uploading temperature data... ", end='', flush=True)
    ret = zrq.request_save()
    if config['verbose']: print("success")
    if ret: return True

  elif cmd == "select":
    if config['verbose']: print("loading temperature data... ", end='', flush=True)
    recs = zrq.request_select()
    if config['verbose']: print("success")
    if ret: return recs
    for rec in recs: print(show_record(rec)) # TODO only few records?

  elif cmd == "check":
    recs = execute_command(zrq, config, "select", ret=True)

    now = datetime.now(zrq.TIME_ZONE)
    checkpoint = datetime.combine(now, time(12,0), now.tzinfo)
    if (now - checkpoint).total_seconds() < 0:
      checkpoint = datetime.combine(now, time(0,0), now.tzinfo)

    check = any(rec['timestamp'] >= checkpoint for rec in recs)
    if config['verbose']: print("temperature already recorded" if check else "no record yet")
    if ret: return check # TODO report with exit status?

  elif cmd == "update":
    if not execute_command(zrq, config, "check", ret=True):
      execute_command(zrq, config, 'save')

  else: raise NotImplementedError(cmd)

def routine_execute_command(zrq, config, cmd, chance=2):
  while chance > 0:
    try:
      execute_command(zrq, config, cmd)
      break # success
    except ConnectionRefusedError: # re-login needed
      if config['verbose']: print("login cookie rejected")
      chance -= 1
      routine_login(zrq, config)
      routine_role(zrq, config)
    except NotImplementedError as e:
      print(f"Unknown command '{cmd}'.", file=sys.stderr)
      print(f"Use 'help' command to see usage.", file=sys.stderr)
      exit(5)

def routine_config_command(path):
  if not path:
    print(DEFAULT_CONFIG_PATH)
    return

  config = {}
  for (f,v) in CONFIG_SCHEME.items():
    config[f] = None if isinstance(v, type) else v

  try:
    with sys.stdout if path == '-' else open(path, "wt") as f:
      json.dump(config, f, indent = 2)
      print("", file=f)
  except OSError as e:
    print(f"Error while writing to config file '{path}'.", file=sys.stderr)
    print(e, file=sys.stderr)
    exit(6)


import os
import sys

DEFAULT_CONFIG_PATH = os.environ['HOME']+"/.emetic_config"
DEFAULT_CACHE_PATH  = os.environ['HOME']+"/.emetic_cache"

CONFIG_SCHEME = {
  'verbose': True,
  'username': str,
  'b64_password': str,
  'cache_path': DEFAULT_CACHE_PATH,
  'temperature': 36.5,
  'cough': False,
  'sore_throat': False,
  'dyspnea': False,
  'fever': False,
  'no_smell_or_taste': False,
  'other_symptoms': False,
}

VERSION_STR = '0.1.0'

HELP_MSG = """
emeic - upload & view temperature data on zeus.gist.ac.kr

Usage: emetic <command> [config_path]

Commands:
    save	Upload temperature data as configured
    select	View temperature data of this month
    check	Check if temperature data has already been uploaded
    update	Upload temperature data only if not have been yet
    config	Create config file with filled with default values
    version	Print program version
    help	Print this help message

  *NOTE* 'check' is glorified 'select'. 'update' is 'check' + 'save'.

Config:
  config_path is optional. If omitted, default path will be used.
  config_file is JSON format. Most of the fields have defaults.
  The only required fields are 'username' and 'b64_password'.
  If config_path is -, config is read/written from/to stdin/stdout.
  Invoke 'config' with explicitly empty path to get default path.

  Brief explanation for each fields:
    'username' and 'b64_password'  are required as string.
      set 'b64_password' with `echo -n '<password>' | base64`.
    'cough', 'sore_throat', 'dyspnea', 'fever', 'no_smell_or_taste'
      and 'other_symptoms' are boolean switches for symptoms.
    'temperature' is float value for body temperature.
    'verbose' enables printing progress to stdout when set(default).
    'cache_path'. cache contains login token cookie, user info, etc.
      emetic logins or querys  per each request when set to ''.

  *NOTE* setting 'verbose':false does not prevent emetic to report
    error messages to stderr. Also, 'select' and 'help' commands
    print to stdout regardless of 'verbose' option.

Examples:
    $ emetic config -                # print default config setting
    $ emetic config ""               # print default config_path
    $ emetic config path/to/cfg      # create default cfg at the path
    $ emetic select                  # view records with default cfg
    $ emetic check - < path/to/cfg   # check if upload needed
    $ emetic update paht/to/cfg      # upload data if needed

  *NOTE* you can use separate cfg for two students on a same machine

  To make emetic run regularly, you may use cron(8) service.
  `$ crontab -e` then paste following lines to the opened editor.
    SHELL=/bin/bash
    0 10 * * * sleep ${RANDOM:0:2}m; emetic update
    0 20 * * * sleep ${RANDOM:0:2}m; emetic update
  It will run `emetic update` command at 10:00 and 20:00 every day
  with random delay under 100 miniutes.
"""


if __name__ == "__main__":
  (cmd, config_path) = routine_args(sys.argv)
  if cmd == 'config':
    routine_config_command(config_path)
    exit(0)
  if cmd == 'version':
    print(VERSION_STR)
    exit(0)
  if cmd == 'help':
    print(HELP_MSG)
    exit(0)

  config = routine_load_config(config_path)
  cache  = routine_load_cache(config['cache_path'])
  with ZeusRequest(cache) as zrq:
    routine_execute_command(zrq, config, cmd)
    routine_store_cache(zrq.get_cache(), config)
