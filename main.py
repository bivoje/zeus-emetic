#!/usr/bin/env python3

import http.client
import json
from urllib.parse import urlencode, unquote # urlparse, parse_qs
from datetime import datetime, time, timezone, timedelta


#http://docs.tobesoft.com/advanced_development_guide_nexacro_17_ko#a5e1e2fb1080ae59
def nexacro_ssv_encode(info, enc="utf-8"):
  rs = '\x1e' # record separator
  return f"SSV:{enc}{rs}" + rs.join(f"{f}={v}" for (f,v) in info)

# TODO use regex if we want smaller code
def nexacro_ssv_check_header(s):
  ss = s.split(b':')
  if len(ss) > 0 and ss[0] == b'SSV':
    if len(ss) > 1:
      if ss[1] not in [b"ascii", b"utf-8"]:
        raise ValueError(f"unrecognized encoding '{s}'")
    return
  raise ValueError(f"header is not SSV format '{s}'")

def nexacro_ssv_decode_typelen(s):
  ss = s.split(b'(')
  if len(ss) > 0:
    if len(ss) > 1:
      if len(ss[1]) == 0 or ss[1][-1] != b')':
        raise ValueError(f"variable type is malformed '{s}'")
      l = 0
      try: l = int(ss[1][0:-1])
      except ValueError as e:
        raise ValueError(f"invalid length specifier '{ss[1][0:-1]}'")
      return (ss[0], l)
    return (ss[0], None)
  raise ValueError(f"variable type is not SSV format '{s}'")

def nexacro_ssv_decode_vid(s):
  ss = s.split(b':')
  if len(ss) > 0:
    if ss[0] == b'':
      raise ValueError(f"empty variable name in '{s}'")
    if len(ss) > 1:
      (t,l) = nexacro_ssv_decode_typelen(ss[1])
      return (ss[0], t, l)
    return (ss[0], None, None)
  raise ValueError(f"variable id is not SSV format '{s}'")

def nexacro_ssv_decode_variable(s):
  ss = s.split(b'=')
  if len(ss) > 0:
    (vid, t, l)  = nexacro_ssv_decode_vid(ss[0])
    if len(ss) > 1:
      return (vid, ss[1], t, l)
    return (vid, None, t, l)
  raise ValueError(f"variable is not SSV format '{s}'")

def nexacro_ssv_decode_dataset(vs, i):
  if len(vs) <= i:
    raise ValueError(f"imcomplete dataset at {i}'th record")
  ss = vs[i].split(b':')
  if len(ss) < 2 or ss[0] != b'Dataset':
    raise ValueError(f"malformed dataset header '{vs[i]}'")
  if ss[1] == b'':
    raise ValueError(f"empty dataset id in '{vs[i]}'")
  did = ss[1]
  i += 1

  if len(vs) <= i:
    raise ValueError(f"imcomplete dataset at {i}'th record")
  if vs[i][0:7] == b'_Const_':
    ss = vs[i].split(b'\x1f')
    if len(ss) < 2 or ss[0] != b'_Const_':
      raise ValueError(f"malformed const column infos '{vs[i]}'")
    for s in ss[1:]:
      (cid, v, t, l) = nexacro_ssv_decode_variable(s)
      # TODO utilize ???
    i += 1

  if len(vs) <= i:
    raise ValueError(f"imcomplete dataset at {i}'th record")
  ss = vs[i].split(b'\x1f')
  if len(ss) < 2 or ss[0] != b'_RowType_':
    raise ValueError(f"malformed column infos '{vs[i]}'")
  for s in ss[1:]:
    pass
    #(cid, v, t, l) = nexacro_ssv_decode_variable(s)
    # TODO 3 type fields possible
    # TODO utilize
  i += 1

  rec = []
  if len(vs) <= i:
    raise ValueError(f"imcomplete dataset at {i}'th record")
  while vs[i] != b'':
    ss = vs[i].split(b'\x1f')
    if len(ss) < 2:
      raise ValueError(f"malformed dataset row '{vs[i]}'")
    if ss[0] not in b'NIUDO':
      raise ValueError(f"unrecognized rowtype in '{vs[i]}'")
    rec.append([None if x == b'\x03' else x for x in ss])
    i += 1
    if len(vs) <= i:
      raise ValueError(f"imcomplete dataset at {i}'th record")

  i += 1
  return ((did, rec), i)


def nexacro_ssv_decode(bs):
  vs = bs.split(b'\x1e')
  nexacro_ssv_check_header(vs[0])

  ret = {}
  i = 1
  while i < len(vs):
    if i == len(vs)-1 and vs[i] == b'':
      break
    elif vs[i][0:7] == b'Dataset':
      ((did, rec), i) = nexacro_ssv_decode_dataset(vs, i)
      ret[did] = rec
    else:
      (vid, value, t, l) = nexacro_ssv_decode_variable(vs[i])
      ret[vid] = value
      i += 1

  return ret


class ZeusRequest:

  # static vars
  TIME_ZONE = timezone(timedelta(hours=9))

  BASE_URL = "zeus.gist.ac.kr"

  LOGIN_PATH  = "/sys/login/auth.do?callback="
  SAVE_PATH   = "/amc/amcDailyTempRegE/save.do"
  SELECT_PATH = "/amc/amcDailyTempRegE/select.do"

  SSV_GUBUN  = "AA"
  SSV_DEPTCD = "0160"
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

  def __init__(self, cached_cookies={}):
    self.conn = http.client.HTTPSConnection(self.BASE_URL);
    self.cookies = cached_cookies
    self.last_response = None
    self.last_data = None

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


  def request_select(self):
    if 'WMONID' not in self.cookies:
      raise ConnectionRefusedError # need log-in

    info = [
      ('WMONID',    self.cookies['WMONID']),
      ('dept_cd',   self.SSV_DEPTCD),
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

    dept = 1; name = 2; stdno = 3; date = 4;
    time = 5; temp = 6; sympt = 7;
    spc_ctnt = 13; gubun = 14 #? = 15
    recs = list(map(lambda row: {
      'timestamp': datetime.strptime(row[date]+row[time], '%Y%m%d%H:%M').replace(tzinfo=self.TIME_ZONE),
      'temperature': float(row[temp]),
      'symptoms': "".join("O" if x else "_" for x in row[sympt:sympt+6]),
      'significance': row[spc_ctnt]
      }, map(lambda row: [v.decode("utf-8") for v in row], ret[b'dsMain'])))
    return recs


  def request_save(self, student_id, symp={'temp':36.5}):
    if 'WMONID' not in self.cookies:
      raise ConnectionRefusedError # need log-in

    info = [
      ('WMONID',    self.cookies['WMONID']),
      ('dept_cd',   self.SSV_DEPTCD),
      ('mbr_no',    student_id),
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


def show_record(rec):
  s_date = rec['timestamp'].strftime('%Y-%m-%d')
  s_time = rec['timestamp'].strftime('%H:%M')
  return "\t".join([
    s_date, s_time, str(rec['temperature']),
    rec['symptoms'], rec['significance']
  ])

def routine_args(argv):
  if len(argv) <= 1:
    print("RTFM!", file=sys.stderr)
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

  DEFAULT_CONFIG = {
    'verbose': True,
    'username': str,
    'password': str,
    'student_id': str,
    'cookie_path': DEFAULT_COOKIE_PATH,
    'temperature': 36.5,
    'cough': False,
    'sore_throat': False,
    'dyspnea': False,
    'fever': False,
    'no_smell_or_taste': False,
    'other_symptoms': False,
  #}.update(config_loaded)
  }

  config = {}

  for (k,v) in DEFAULT_CONFIG.items():
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

  if config_loaded: # config_loaded \notin DEFAULT_CONFIG
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

def routine_load_cookies(path):
  try:
    with open(path, "rt") as f:
      return json.load(f)
  except (FileNotFoundError, json.decoder.JSONDecodeError):
    return {} # especially when path == ''; indicating no cache store
  except OSError as e:
    print(f"Error while reading cookie file '{path}'.", file=sys.stderr)
    print(e, file=sys.stderr)
    return {}

def routine_store_cookies(cookies, config):
  try:
    with open(config['cookie_path'], "wt") as f:
      json.dump(cookies, f, indent=2)
  except FileNotFoundError as e:
    return # especially when path == ''; indicating no cache store
  except OSError as e:
    print(f"Error while writing to cookie file '{path}'.", file=sys.stderr)
    print(e, file=sys.stderr)

def routine_login(zrq, config):
  if config['verbose']: print("try loging in... ", end='', flush=True)
  try:
    ret = zrq.request_login(config['username'], config['password'])
  except ConnectionError as e:
    if config['verbose']: print("failed")
    print(e, file=sys.stderr)
    exit(4)
  if config['verbose']: print("success")

def execute_command(zrq, config, cmd, ret=False):
  if cmd == "save":
    if config['verbose']: print("uploading temperature data... ", end='', flush=True)
    ret = zrq.request_save(config['student_id'])
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
    if config['verbose']: print("temperature already recored" if check else "no record yet")
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
    except NotImplementedError as e:
      if config['verbose']: print(f"Unknown command '{cmd}'.")
      exit(5)


import os
import sys

DEFAULT_CONFIG_PATH = os.environ['HOME']+"/.emetic_config"
DEFAULT_COOKIE_PATH = os.environ['HOME']+"/.emetic_cookie"

if __name__ == "__main__":
  (cmd, config_path) = routine_args(sys.argv)
  config = routine_load_config(config_path)
  cookies = routine_load_cookies(config['cookie_path'])
  with ZeusRequest(cookies) as zrq:
    zrq = ZeusRequest(cookies)
    routine_execute_command(zrq, config, cmd)
    routine_store_cookies(zrq.cookies, config)
