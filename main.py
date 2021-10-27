#!/usr/bin/env python3

import http.client
import json
from urllib.parse import urlencode, unquote # urlparse, parse_qs
from datetime import datetime, timezone, timedelta

# for debugging
errdat = None
def sed(dat):
  global errdat
  errdat = dat

BASE_URL = "zeus.gist.ac.kr"

LOGIN_PATH  = "/sys/login/auth.do?callback="
SAVE_PATH   = "/amc/amcDailyTempRegE/save.do"
SELECT_PATH = "/amc/amcDailyTempRegE/select.do"

SSV_GUBUN  = "AA"
SSV_DEPTCD = "0160"
SSV_PGKEY  = "PERS07^PERS07_08^005^AmcDailyTempRegE"

TIME_ZONE = timezone(timedelta(hours=9))

# copy & pasted from chrome inspector
# then :s/^\([^:]\+\):\s*\(.\+\)$/"\1": '\2',/g
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

COOKIES = {}

def cookie_monster(headers):
  for cookie in (hv for (hf,hv) in headers if hf == "Set-Cookie"):
    cookie_content = cookie.split(';')[0]
    (cf,cv) = cookie_content.split('=', 1)
    COOKIES[cf.strip()] = cv.strip()

def cookie_demon():
  return "; ".join(f"{cf}={cv}" for (cf,cv) in COOKIES.items())

def decode_xml_error(bs):
  import xml.etree.ElementTree as elemTree
  ret = elemTree.fromstring(bs)
  err = ret.find(".//*[@id='ErrorMsg']").text
  return err


#http://docs.tobesoft.com/advanced_development_guide_nexacro_17_ko#a5e1e2fb1080ae59
def nexacro_ssv_encode(info, enc="utf-8"):
  rs = '\x1e' # record separator
  return f"SSV:{enc}{rs}" + rs.join(f"{f}={v}" for (f,v) in info)

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


def request_login(conn, user_id, user_pw):
  params = urlencode({'login_id':user_id, 'login_pw':user_pw}, safe='!*()')
  headers = BASE_HEADERS.copy()
  headers["Referer"] = 'https://' + BASE_URL + '/sys/main/login.do'

  conn.request("POST", LOGIN_PATH, params, headers)
  response = conn.getresponse()
  head = response.getheaders()
  cookie_monster(head)
  data = response.read()

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

  if 'WMONID' not in COOKIES or 'ZSESSIONID' not in COOKIES:
    raise ConnectionError(f"login successfully failed. '{head}'")

  return True


def select_dumps(ret):
  dept = 1; name = 2; stdno = 3; date = 4;
  time = 5; temp = 6; sympt = 7;
  spc_ctnt = 13; gubun = 14
  #?        = 15
  for row_ in ret[b'dsMain'][0:10]:
    row = [v.decode("utf-8") for v in row_]
    s_date = f"{row[date][0:4]}-{row[date][4:6]}-{row[date][6:8]}"
    s_sympt= "".join("O" if x else "_" for x in row[sympt:sympt+6])
    print("\t".join([s_date, row[time], row[temp], s_sympt, row[spc_ctnt]]))

def request_select(conn):
  assert('WMONID' in COOKIES)
  info = [
    ('WMONID',    COOKIES['WMONID']),
    ('dept_cd',   SSV_DEPTCD),
    ('chk_dt',    datetime.now(TIME_ZONE).strftime('%Y%m')),
    ('pg_key',    SSV_PGKEY),
    ('page_open_time', ""),
    ('page_open_time_on', datetime.now(TIME_ZONE).strftime('%Y%m%d%H%M%S%f')),
  ]

  params = nexacro_ssv_encode(info)
  headers = BASE_HEADERS.copy()
  headers["Referer"] = 'https://' + BASE_URL + '/index.html'
  headers["Accept"] = "*/*"
  headers["Content-Type"] = "text/plain;charset=UTF-8"
  headers["Cookie"] = cookie_demon()
  headers.pop("X-Requested-With", None)

  conn.request("POST", SELECT_PATH, params, headers)
  response = conn.getresponse()
  head = response.getheaders()
  cookie_monster(head)
  data = response.read()

  if response.status != 200:
    raise ConnectionError(
      f"server returned {response.status}, {response.reason}")

  ret = nexacro_ssv_decode(data)
  if b'dsMain' not in ret:
    raise ValueError(f"expecting 'dsMain' got '{ret}'")
  return ret


def request_save(conn, student_id, symp={'temp':36.5}):
  assert('WMONID' in COOKIES)
  info = [
    ('WMONID',    COOKIES['WMONID']),
    ('dept_cd',   SSV_DEPTCD),
    ('mbr_no',    student_id),
    ('chk_dt',    datetime.now(TIME_ZONE).strftime('%Y-%m-%d')),
    ('temp',      f"{symp['temp']:.1f}"), # TODO catch error
    ('sympt_1',   'Y' if symp.get('cough', False) else 'N'),
    ('sympt_2',   'Y' if symp.get('soret', False) else 'N'),
    ('sympt_3',   'Y' if symp.get('dyspn', False) else 'N'),
    ('sympt_4',   'Y' if symp.get('fever', False) else 'N'),
    ('sympt_5',   'Y' if symp.get('losat', False) else 'N'),
    ('sympt_6',   'Y' if symp.get('orsym', False) else 'N'),
    ('spc_ctnt',  symp.get('special', "")),
    ('gubun',     SSV_GUBUN),
    ('pg_key',    SSV_PGKEY),
    ('page_open_time', ""),
    ('page_open_time_on', datetime.now(TIME_ZONE).strftime('%Y%m%d%H%M%S%f')),
  ]

  params = nexacro_ssv_encode(info)
  headers = BASE_HEADERS.copy()
  headers["Referer"] = 'https://' + BASE_URL + '/index.html'
  headers["Accept"] = "*/*"
  headers["Content-Type"] = "text/plain;charset=UTF-8"
  headers["Cookie"] = cookie_demon()
  headers.pop("X-Requested-With", None)

  conn.request("POST", SAVE_PATH, params, headers)
  response = conn.getresponse()
  head = response.getheaders()
  cookie_monster(head)
  data = response.read()

  if response.status != 200:
    raise ConnectionError(
      f"server returned {response.status}, {response.reason}")

  ret = nexacro_ssv_decode(data)
  return ret # TODO validity check?


import os

DEFAULT_CONFIG_PATH = os.environ['HOME']+"/.emetic_config"
DEFAULT_COOKIE_PATH = os.environ['HOME']+"/.emetic_cookie"

if __name__ == "__main__":
  import sys

  if len(sys.argv) <= 1:
    print("RTFM!")
    exit(1)

  if len(sys.argv) <= 2:
    config_path = DEFAULT_CONFIG_PATH
  else:
    conifg_path = sys.argv[2]

  try:
    with open(config_path, "rt") as f:
      config_loaded = json.load(f)
  except OSError as e:
    print(f"error while reading config file at {config_path}")
    print(e)
    exit(3)

  config = {
    'username': "", 'password': "",
    'student_id': "",
    'cookie_path': DEFAULT_COOKIE_PATH,
    'temperature': "36.5",
    # sympts? TODO
  }
  #}.update(config_loaded)

  for (k,v) in config_loaded.items():
    if not isinstance(v, str):
      print(f"config value for entry '{k}' is not string")
      # TODO temperature validating?
      exit(3)
    if k not in config:
      print(f"unrecognized config entry '{k}'")
      exit(3)
    config[k] = v

  conn = http.client.HTTPSConnection(BASE_URL);
  request_login(conn, config['username'], config['password'])

  if sys.argv[1] == "save":
    ret = request_save(conn, config['student_id'])

  elif sys.argv[1] == "select":
    ret = request_select(conn)
    select_dumps(ret)

  conn.close()
