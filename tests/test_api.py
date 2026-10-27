from email.message import Message
import json, os, shutil, unittest, uuid
from pathlib import Path
from datetime import date, timedelta
os.environ['CASEWORK_DB']='sqlite'
from backend import api

class BackendTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(__file__).parent/('.tmp-'+uuid.uuid4().hex);self.tmp.mkdir();api.DB_PATH=self.tmp/'test.db';api._sessions.clear();api.init_db();api.install_views()
  c=api.connect();cur=c.cursor();cur.execute("INSERT INTO users(username,password_hash,name,role,active,created_at) VALUES(?,?,?,?,?,?)",('manager',api.hash_password('manager-test-password'),'Test Manager','Management Head',True,api.utcnow()));cur.execute("INSERT INTO users(username,password_hash,name,role,active,created_at) VALUES(?,?,?,?,?,?)",('operator',api.hash_password('operator-test-password'),'Test Operator','Operator',True,api.utcnow()));c.commit();c.close();self.admin=self.login('manager','manager-test-password');self.operator=self.login('operator','operator-test-password')
 def tearDown(self):shutil.rmtree(self.tmp)
 def call(self,method,path,body=None,cookie=None):
  h=api.API.__new__(api.API);h.headers=Message()
  if cookie:h.headers['Cookie']=cookie
  from urllib.parse import parse_qs,urlparse
  try:status,data,headers=h.dispatch(method,urlparse(path).path,parse_qs(urlparse(path).query),body or {})
  except ValueError as e:return 400,{'error':str(e)},{}
  except api.sqlite3.IntegrityError as e:return 409,{'error':'That value is already in use.'},{}
  except Exception as e:raise
  return status,data,headers
 def login(self,user,password):
  status,data,h=self.call('POST','/api/auth/login',{'username':user,'password':password});self.assertEqual(status,200);return h['Set-Cookie'].split(';',1)[0]
 def test_health_and_authentication(self):
  status,data,_=self.call('GET','/api/health');self.assertEqual(status,200);self.assertEqual(data['database'],'connected')
  self.assertEqual(self.call('GET','/api/cases')[0],401)
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'manager','password':'wrong-password'})[0],401)
  self.assertEqual(self.call('GET','/api/auth/me',cookie=self.admin)[0],200)
 def test_login_throttling_uses_persisted_failures_and_expires_after_window(self):
  payload={'username':'manager','password':'incorrect'}
  for _ in range(4):self.assertEqual(self.call('POST','/api/auth/login',payload)[0],401)
  status,data,headers=self.call('POST','/api/auth/login',payload);self.assertEqual(status,429);self.assertEqual(data['code'],'login_locked');self.assertEqual(int(headers['Retry-After']),api.LOGIN_WINDOW)
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'manager','password':'manager-test-password'})[0],429)
  conn=api.connect();cur=conn.cursor();cur.execute('SELECT COUNT(*) n FROM login_attempts WHERE succeeded=0');self.assertEqual(api.one_dict(cur)['n'],5);cur.execute('UPDATE login_attempts SET attempted_at=?,locked_until=? WHERE locked_until IS NOT NULL',((api.datetime.now(api.timezone.utc)-api.timedelta(seconds=api.LOGIN_WINDOW+5)).isoformat(timespec='seconds'),(api.datetime.now(api.timezone.utc)-api.timedelta(seconds=1)).isoformat(timespec='seconds')));conn.commit();conn.close()
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'manager','password':'manager-test-password'})[0],200)
 def test_idle_session_expiry_returns_clear_cookie_and_message_code(self):
  token=self.admin.split('=',1)[1];conn=api.connect();cur=conn.cursor();cur.execute('UPDATE sessions SET last_seen_at=? WHERE token_hash=?',((api.datetime.now(api.timezone.utc)-api.timedelta(seconds=api.SESSION_IDLE_TTL+1)).isoformat(timespec='seconds'),api.hashlib.sha256(token.encode()).hexdigest()));conn.commit();conn.close()
  status,data,headers=self.call('GET','/api/auth/me',cookie=self.admin);self.assertEqual(status,401);self.assertEqual(data['code'],'session_expired');self.assertIn('expired',data['error'].lower());self.assertIn('Max-Age=0',headers['Set-Cookie'])
 def test_change_password_revokes_sessions_and_requires_reauthentication(self):
  status,data,headers=self.call('POST','/api/auth/change-password',{'current_password':'wrong','new_password':'a-new-long-password'},self.admin);self.assertEqual(status,400)
  self.assertEqual(self.call('POST','/api/auth/change-password',{'current_password':'manager-test-password','new_password':'short'},self.admin)[0],400)
  status,data,headers=self.call('POST','/api/auth/change-password',{'current_password':'manager-test-password','new_password':'manager-new-long-password'},self.admin);self.assertEqual(status,200);self.assertIn('Max-Age=0',headers['Set-Cookie'])
  self.assertEqual(self.call('GET','/api/auth/me',cookie=self.admin)[0],401)
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'manager','password':'manager-test-password'})[0],401)
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'manager','password':'manager-new-long-password'})[0],200)
 def test_management_head_only_user_management(self):
  conn=api.connect();cur=conn.cursor();cur.execute("INSERT INTO users(username,password_hash,name,role,active,created_at) VALUES(?,?,?,?,?,?)",('administrator',api.hash_password('admin-test-password'),'Test Administrator','Administrator',True,api.utcnow()));cur.execute("SELECT id FROM users WHERE username='manager'");head_id=api.one_dict(cur)['id'];conn.commit();conn.close();administrator=self.login('administrator','admin-test-password')
  for method,path,body,cookie in [('GET','/api/users',None,administrator),('POST','/api/users',{'username':'nope','name':'Nope','password':'long-password-123','role':'Operator'},administrator),('PUT','/api/users/1',{'role':'Operator'},administrator),('GET','/api/users',None,self.operator)]:self.assertEqual(self.call(method,path,body,cookie)[0],403)
  status,created,_=self.call('POST','/api/users',{'username':'new.operator','name':'New Operator','password':'long-password-123','role':'Operator'},self.admin);self.assertEqual(status,201);uid=created['item']['id']
  self.assertEqual(self.call('PUT',f'/api/users/{uid}',{'role':'Administrator'},self.admin)[1]['item']['role'],'Administrator')
  self.assertEqual(self.call('PUT',f'/api/users/{uid}',{'active':False},self.admin)[1]['item']['active'],False)
  self.assertEqual(self.call('POST','/api/auth/login',{'username':'new.operator','password':'long-password-123'})[0],401)
  self.assertEqual(self.call('PUT',f'/api/users/{head_id}',{'active':False},self.admin)[0],409)
 def test_sqlite_indexes_cover_filters_and_foreign_keys(self):
  conn=api.connect();cur=conn.cursor();found={}
  for table in ('cases','persons','sessions'):
   cur.execute(f'PRAGMA index_list({table})');found[table]={row['name'] for row in api.cursor_dicts(cur)}
  conn.close()
  self.assertTrue({'idx_cases_status','idx_cases_category','idx_cases_location','idx_cases_status_category_opened','idx_cases_officer'}<=found['cases'])
  self.assertTrue({'idx_persons_name','idx_persons_case'}<=found['persons'])
  self.assertIn('idx_sessions_user_id',found['sessions'])
 def test_evidence_crud_transfer_timeline_and_append_only_custody(self):
  self.call('POST','/api/cases',{'id':'EVIDENCE-CASE','title':'Evidence test case','category':'Test','status':'Active'},self.admin)
  _,first,_=self.call('POST','/api/officers',{'name':'Collector Officer','role':'Evidence Officer','badge':'EVID-COLLECT'},self.admin)
  _,second,_=self.call('POST','/api/officers',{'name':'Receiving Officer','role':'Evidence Officer','badge':'EVID-RECEIVE'},self.admin)
  _,third,_=self.call('POST','/api/officers',{'name':'Second Receiver','role':'Evidence Officer','badge':'EVID-SECOND'},self.admin)
  payload={'description':'Fictional sealed evidence bag','type':'Physical item','hash':'a'*64,'storage_path':'evidence/EVIDENCE-CASE/item-1.bin','collected_by':first['item']['id']}
  self.assertEqual(self.call('POST','/api/cases/EVIDENCE-CASE/evidence',{**payload,'hash':'bad'},self.admin)[0],400)
  status,created,_=self.call('POST','/api/cases/EVIDENCE-CASE/evidence',payload,self.admin);self.assertEqual(status,201);eid=created['item']['id'];self.assertEqual(len(created['item']['custody_timeline']),1)
  updated={**payload,'description':'Updated evidence description'};self.assertEqual(self.call('PUT',f'/api/evidence/{eid}',updated,self.admin)[0],200)
  self.assertEqual(self.call('PUT',f'/api/evidence/{eid}',{**updated,'hash':'b'*64},self.admin)[0],409)
  self.assertEqual(self.call('POST',f'/api/evidence/{eid}/transfer',{'to_officer':second['item']['id'],'purpose':'Lab analysis'},self.admin)[0],200)
  status,moved,_=self.call('POST',f'/api/evidence/{eid}/transfer',{'to_officer':third['item']['id'],'purpose':'Return from laboratory'},self.admin);self.assertEqual(status,200)
  timeline=moved['item']['custody_timeline'];self.assertEqual(len(timeline),3);self.assertEqual(timeline[1]['from_officer_name'],'Collector Officer');self.assertEqual(timeline[1]['to_officer_name'],'Receiving Officer');self.assertEqual(timeline[2]['from_officer_name'],'Receiving Officer')
  self.assertEqual(self.call('DELETE',f'/api/evidence/{eid}',cookie=self.admin)[0],409)
  self.assertEqual(self.call('POST',f'/api/evidence/{eid}/transfer',{'to_officer':third['item']['id'],'purpose':'Duplicate holder'},self.admin)[0],409)
  self.assertEqual(self.call('POST',f'/api/evidence/{eid}/transfer',{'to_officer':first['item']['id'],'purpose':'Operator cannot transfer'},self.operator)[0],403)
  conn=api.connect();cur=conn.cursor()
  with self.assertRaises(api.sqlite3.IntegrityError):cur.execute('UPDATE custody_log SET purpose=? WHERE evidence_id=?',('tampered',eid))
  conn.rollback()
  with self.assertRaises(api.sqlite3.IntegrityError):cur.execute('DELETE FROM custody_log WHERE evidence_id=?',(eid,))
  conn.rollback();conn.close()
  self.assertEqual(self.call('GET','/api/cases/EVIDENCE-CASE/evidence',cookie=self.admin)[1]['items'][0]['id'],eid)
  disposable={**payload,'description':'Untransferred disposable evidence'}
  _,untransferred,_=self.call('POST','/api/cases/EVIDENCE-CASE/evidence',disposable,self.admin)
  self.assertEqual(self.call('DELETE',f"/api/evidence/{untransferred['item']['id']}",cookie=self.admin)[0],200)
  self.assertEqual(self.call('POST','/api/cases/MISSING/evidence',payload,self.admin)[0],404)
 def test_court_hearing_crud_dashboard_window_and_permissions(self):
  self.call('POST','/api/cases',{'id':'HEARING-CASE','title':'Hearing test case','category':'Test','status':'Active'},self.admin)
  today=date.today()
  def add(ref,offset,status='Scheduled'):
   self.call('POST','/api/cases',{'id':ref,'title':ref,'category':'Test','status':'Active'},self.admin)
   code,result,_=self.call('POST',f'/api/cases/{ref}/hearings',{'court':'District Court 4','hearing_date':(today+timedelta(days=offset)).isoformat(),'status':status,'outcome':'','notes':'Fictional hearing'},self.admin)
   self.assertEqual(code,201);return result['item']
  in_window=add('HEARING-CASE',3);adjourned=add('HEARING-ADJOURNED',14,'Adjourned');completed=add('HEARING-COMPLETED',5,'Completed');add('HEARING-FUTURE',15)
  self.assertEqual(self.call('GET','/api/cases/HEARING-CASE/hearings',cookie=self.admin)[1]['items'][0]['id'],in_window['id'])
  status,updated,_=self.call('PUT',f"/api/hearings/{in_window['id']}",{'court':'Updated District Court','hearing_date':(today+timedelta(days=10)).isoformat(),'status':'Adjourned','outcome':'New date set','notes':'Updated notes'},self.admin)
  self.assertEqual(status,200);self.assertEqual(updated['item']['outcome'],'New date set')
  self.assertEqual(self.call('GET',f"/api/hearings/{in_window['id']}",cookie=self.admin)[1]['item']['court'],'Updated District Court')
  self.assertEqual(self.call('PUT',f"/api/hearings/{in_window['id']}",{'court':'Bad date','hearing_date':'not-a-date','status':'Scheduled'},self.admin)[0],400)
  self.assertEqual(self.call('PUT',f"/api/hearings/{in_window['id']}",{'court':'Bad status','hearing_date':today.isoformat(),'status':'Unknown'},self.admin)[0],400)
  dashboard=self.call('GET','/api/dashboard',cookie=self.admin)[1];refs={item['case_reference'] for item in dashboard['upcoming_hearings']}
  self.assertIn('HEARING-CASE',refs);self.assertIn('HEARING-ADJOURNED',refs);self.assertNotIn('HEARING-COMPLETED',refs);self.assertNotIn('HEARING-FUTURE',refs)
  self.assertEqual(self.call('POST','/api/cases/HEARING-CASE/hearings',{'court':'No access','hearing_date':today.isoformat(),'status':'Scheduled'},self.operator)[0],403)
  self.assertEqual(self.call('DELETE',f"/api/hearings/{in_window['id']}",cookie=self.operator)[0],403)
  self.assertEqual(self.call('DELETE',f"/api/hearings/{in_window['id']}",cookie=self.admin)[0],200)
  self.assertEqual(self.call('GET',f"/api/hearings/{in_window['id']}",cookie=self.admin)[0],404)
  self.assertEqual(self.call('GET','/api/cases/NO-CASE/hearings',cookie=self.admin)[0],404)
 def test_case_crud_duplicate_search_dashboard_reports_activity(self):
  status,off,_=self.call('POST','/api/officers',{'name':'Demo Officer','role':'Detective','badge':'TEST-1'},self.admin);self.assertEqual(status,201)
  case={'id':'TEST-CASE-001','title':'Fictional test case','category':'Burglary','status':'Active','officer':'Demo Officer','date':'2026-10-26','location':'Test District'}
  status,created,_=self.call('POST','/api/cases',case,self.admin);self.assertEqual(status,201);self.assertEqual(created['item']['id'],case['id'])
  self.assertEqual(self.call('POST','/api/cases',case,self.admin)[0],409)
  self.assertEqual(self.call('GET','/api/cases?q=TEST-CASE-001',cookie=self.admin)[1]['total'],1)
  updated={**case,'title':'Updated fictional case','status':'Closed'};status,result,_=self.call('PUT','/api/cases/TEST-CASE-001',updated,self.admin);self.assertEqual(status,200);self.assertEqual(result['item']['status'],'Closed')
  history_status,history,_=self.call('GET','/api/cases/TEST-CASE-001/history',cookie=self.admin);self.assertEqual(history_status,200);self.assertEqual(len(history['items']),3);self.assertTrue(all(item['changed_by']=='manager' for item in history['items']));self.assertTrue(any(item['type']=='status' and item['old_status']=='Active' and item['new_status']=='Closed' for item in history['items']))
  dashboard=self.call('GET','/api/dashboard',cookie=self.admin)[1];self.assertEqual(dashboard['counts']['total'],1);self.assertEqual(dashboard['counts']['closed'],1)
  reports=self.call('GET','/api/reports',cookie=self.admin)[1];self.assertEqual(reports['total'],1)
  self.assertGreaterEqual(len(self.call('GET','/api/activity',cookie=self.admin)[1]['items']),2)
  blocked=self.call('DELETE','/api/cases/TEST-CASE-001',cookie=self.admin);self.assertEqual(blocked[0],409);self.assertEqual(blocked[1]['error'],'Closed cases cannot be deleted.')
  self.assertEqual(self.call('PUT','/api/cases/TEST-CASE-001',{**updated,'status':'Active'},self.admin)[0],409)
  self.call('POST','/api/cases',{'id':'TEST-DELETE-001','title':'Disposable active case','category':'Other','status':'Active'},self.admin)
  self.assertEqual(self.call('DELETE','/api/cases/TEST-DELETE-001',cookie=self.admin)[0],200)
  c=api.connect();cur=c.cursor();cur.execute("SELECT action,changed_by FROM audit_log WHERE table_name='cases' AND record_key=? ORDER BY id",('TEST-DELETE-001',));deleted_audit=api.cursor_dicts(cur);c.close();self.assertEqual(deleted_audit[-1]['action'],'DELETE');self.assertEqual(deleted_audit[-1]['changed_by'],'manager')
  self.assertEqual(self.call('GET','/api/cases/TEST-CASE-001',cookie=self.admin)[0],200)
  self.assertEqual(self.call('GET','/api/cases/NOT-FOUND/history',cookie=self.admin)[0],404)
 def test_person_officer_foreign_keys_and_operator_permissions(self):
  self.assertEqual(self.call('POST','/api/cases',{'id':'OP-1','title':'no','category':'Other','status':'Active'},self.operator)[0],403)
  self.assertEqual(self.call('POST','/api/persons',{'name':'Fictional','case':'MISSING','age':'35','status':'Unknown','charge':'Example'},self.admin)[0],400)
  self.call('POST','/api/officers',{'name':'Assigned Detective','role':'Detective','badge':'TEST-2'},self.admin)
  self.call('POST','/api/cases',{'id':'LINK-1','title':'Link test','category':'Other','status':'Active','officer':'Assigned Detective'},self.admin)
  status,person,_=self.call('POST','/api/persons',{'name':'Fictional Person','case':'LINK-1','age':'35','status':'Under investigation','charge':'Test charge'},self.admin);self.assertEqual(status,201);self.assertEqual(person['item']['case'],'LINK-1')
  self.assertEqual(self.call('DELETE','/api/officers/1',cookie=self.admin)[0],409)
  self.assertEqual(self.call('GET','/api/officers',cookie=self.operator)[1]['items'][0]['cases'],1)
 def test_person_and_officer_update_delete_and_logout(self):
  self.call('POST','/api/officers',{'name':'Case Officer','role':'Detective','badge':'PERSON-1'},self.admin)
  self.call('POST','/api/cases',{'id':'PERSON-LINK','title':'Link','category':'Other','status':'Active','officer':'Case Officer'},self.admin)
  status,person,_=self.call('POST','/api/persons',{'name':'Sample Subject','case':'PERSON-LINK','age':'32','status':'Unknown','charge':'Fictional charge'},self.admin);self.assertEqual(status,201);pid=person['item']['id']
  status,updated,_=self.call('PUT',f'/api/persons/{pid}',{'name':'Updated Subject','case':'PERSON-LINK','age':'33','status':'Wanted','charge':'Updated charge'},self.admin);self.assertEqual(status,200);self.assertEqual(updated['item']['name'],'Updated Subject')
  self.assertEqual(self.call('DELETE',f'/api/persons/{pid}',cookie=self.admin)[0],200)
  status,officers,_=self.call('GET','/api/officers?q=Case',cookie=self.admin);oid=officers['items'][0]['id']
  status,officer,_=self.call('PUT',f'/api/officers/{oid}',{'name':'Renamed Officer','role':'Senior Detective','badge':'PERSON-1'},self.admin);self.assertEqual(status,200);self.assertEqual(officer['item']['name'],'Renamed Officer')
  # The linked case prevents removal until it is reassigned.
  self.assertEqual(self.call('DELETE',f'/api/officers/{oid}',cookie=self.admin)[0],409)
  self.call('PUT','/api/cases/PERSON-LINK',{'title':'Link','category':'Other','status':'Active','officer':'','date':'','location':''},self.admin)
  self.assertEqual(self.call('DELETE',f'/api/officers/{oid}',cookie=self.admin)[0],200)
  self.assertEqual(self.call('POST','/api/auth/logout',cookie=self.admin)[0],200)
  self.assertEqual(self.call('GET','/api/auth/me',cookie=self.admin)[0],401)
 def test_person_many_to_many_roles_legacy_migration_and_compatibility(self):
  for ref in ('LINK-MANY-A','LINK-MANY-B'):
   self.call('POST','/api/cases',{'id':ref,'title':ref,'category':'Test','status':'Active'},self.admin)
  status,created,_=self.call('POST','/api/persons',{'name':'Multi-linked Person','cases':[{'case_reference':'LINK-MANY-A','role':'suspect'},{'case_reference':'LINK-MANY-B','role':'witness'}],'age':'41','status':'Under investigation','charge':'Test charge'},self.admin)
  self.assertEqual(status,201);pid=created['item']['id'];self.assertEqual(created['item']['case'],'LINK-MANY-A')
  self.assertEqual({(x['case_reference'],x['role']) for x in created['item']['cases']},{('LINK-MANY-A','suspect'),('LINK-MANY-B','witness')})
  status,results,_=self.call('GET','/api/persons?q=LINK-MANY-B',cookie=self.admin);self.assertEqual(status,200);self.assertEqual([x['id'] for x in results['items']],[pid])
  updated=self.call('PUT',f'/api/persons/{pid}',{'name':'Multi-linked Person','cases':[{'case_reference':'LINK-MANY-A','role':'victim'},{'case_reference':'LINK-MANY-B','role':'witness'}],'age':'41','status':'Wanted','charge':'Updated charge'},self.admin)
  self.assertEqual(updated[0],200);self.assertEqual({(x['case_reference'],x['role']) for x in updated[1]['item']['cases']},{('LINK-MANY-A','victim'),('LINK-MANY-B','witness')})
  self.assertEqual(self.call('PUT',f'/api/persons/{pid}',{'name':'Multi-linked Person','cases':[{'case_reference':'LINK-MANY-A','role':'invalid'}],'age':'41','status':'Wanted','charge':'Updated charge'},self.admin)[0],400)
  self.assertEqual(self.call('POST','/api/persons',{'name':'Operator write','cases':[{'case_reference':'LINK-MANY-A','role':'victim'}],'status':'Unknown','charge':'x'},self.operator)[0],403)
  # Simulate a pre-junction legacy row, then initialize again to run the safe data migration.
  conn=api.connect();cur=conn.cursor();cur.execute("INSERT INTO persons(name,case_id,age,status,charge,created_at,updated_at) SELECT 'Legacy Person',id,NULL,'Unknown','Legacy charge',?,? FROM cases WHERE case_ref=?",(api.utcnow(),api.utcnow(),'LINK-MANY-A'));legacy_id=cur.lastrowid;conn.commit();conn.close()
  api.init_db();conn=api.connect();cur=conn.cursor();cur.execute('SELECT case_reference,role FROM case_persons WHERE person_id=?',(legacy_id,));migrated=api.cursor_dicts(cur);conn.close()
  self.assertEqual(migrated,[{'case_reference':'LINK-MANY-A','role':'person_of_interest'}])
  # Legacy single-case clients retain their old request/response contract.
  status,legacy,_=self.call('POST','/api/persons',{'name':'Legacy Client Person','case':'LINK-MANY-B','status':'Unknown','charge':'Old client'},self.admin)
  self.assertEqual(status,201);self.assertEqual(legacy['item']['case'],'LINK-MANY-B');self.assertEqual(legacy['item']['cases'][0]['role'],'person_of_interest')
  self.call('POST','/api/cases',{'id':'LINK-CASCADE','title':'Cascade check','category':'Test','status':'Active'},self.admin)
  _,cascade_person,_=self.call('POST','/api/persons',{'name':'Retained Person','cases':[{'case_reference':'LINK-CASCADE','role':'witness'}],'status':'Unknown','charge':'Cascade check'},self.admin)
  self.assertEqual(self.call('DELETE','/api/cases/LINK-CASCADE',cookie=self.admin)[0],200)
  retained=self.call('GET',f"/api/persons/{cascade_person['item']['id']}",cookie=self.admin)
  self.assertEqual(retained[0],200);self.assertEqual(retained[1]['item']['cases'],[]);self.assertIsNone(retained[1]['item']['case'])
 def test_analytics_window_queries_views_and_csv_exports(self):
  officers=[]
  for name,badge in [('Rank Officer A','RANK-A'),('Rank Officer B','RANK-B'),('Rank Officer C','RANK-C')]:
   officers.append(self.call('POST','/api/officers',{'name':name,'role':'Detective','badge':badge},self.admin)[1]['item'])
  rows=[('AN-JAN-1',officers[0]['name'],'Closed','2026-01-04','Hotspot'),('AN-JAN-2',officers[0]['name'],'Closed','2026-01-14','Hotspot'),('AN-FEB-1',officers[1]['name'],'Closed','2026-02-12','Other'),('AN-MAR-1',officers[1]['name'],'Active','2026-03-04','March Place A'),('AN-MAR-2',officers[1]['name'],'Active','2026-03-12','March Place B'),('AN-MAR-3',officers[2]['name'],'Active','2026-03-21','March Place C')]
  for ref,officer,status,opened,location in rows:
   self.call('POST','/api/cases',{'id':ref,'title':ref,'category':'Test','status':status,'officer':officer,'date':opened,'location':location},self.admin)
  conn=api.connect();cur=conn.cursor()
  for ref,_,_,created,_ in rows:cur.execute('UPDATE cases SET created_at=? WHERE case_ref=?',(f'{created}T12:00:00+00:00',ref))
  conn.commit();conn.close();api.install_views()
  status,data,_=self.call('GET','/api/analytics',cookie=self.admin);self.assertEqual(status,200)
  ranks={row['officer_name']:row['rank'] for row in data['officer_rankings']};self.assertEqual(ranks['Rank Officer A'],1);self.assertEqual(ranks['Rank Officer B'],2);self.assertEqual(ranks['Rank Officer C'],3)
  months={row['month']:row for row in data['monthly_case_change']};self.assertEqual([months[m]['case_change'] for m in ('2026-01','2026-02','2026-03')],[0,-1,2]);self.assertEqual(months['2026-03']['previous_month_cases'],1)
  self.assertEqual(data['location_hotspots'],[{'location':'Hotspot','case_count':2}])
  conn=api.connect();cur=conn.cursor();cur.execute('SELECT COUNT(*) n FROM officer_workload_view');self.assertEqual(api.one_dict(cur)['n'],3);cur.execute('SELECT case_ref FROM public_case_view LIMIT 1');self.assertTrue(api.one_dict(cur));conn.close()
  self.call('POST','/api/persons',{'name':'Repeat Analytics Person','cases':[{'case_reference':'AN-JAN-1','role':'suspect'},{'case_reference':'AN-FEB-1','role':'witness'}],'status':'Unknown','charge':'Analytics test'},self.admin)
  conn=api.connect();cur=conn.cursor();cur.execute("SELECT case_count FROM repeat_persons_view WHERE name=?",('Repeat Analytics Person',));self.assertEqual(api.one_dict(cur)['case_count'],2)
  with self.assertRaises(api.sqlite3.OperationalError):cur.execute('SELECT resolution FROM public_case_view')
  conn.close()
  for kind in ('analytics-officers','analytics-monthly','analytics-hotspots'):
   status,csv,headers=self.call('GET',f'/api/reports/export?type={kind}',cookie=self.admin);self.assertEqual(status,200);self.assertIn(b'\xef\xbb\xbf',csv);self.assertIn(f'casework-{kind}.csv',headers['Content-Disposition'])
 def test_invalid_inputs_and_not_found(self):
  self.assertEqual(self.call('POST','/api/cases',{'id':'','title':'','category':'','status':'Bad'},self.admin)[0],400)
  self.assertEqual(self.call('GET','/api/cases/NOT-FOUND',cookie=self.admin)[0],404)
  self.assertEqual(self.call('POST','/api/officers',{'name':'A','role':'B','badge':'DUP'},self.admin)[0],201)
  self.assertEqual(self.call('POST','/api/officers',{'name':'B','role':'B','badge':'DUP'},self.admin)[0],409)

 def test_assign_close_transfer_and_days_open_routines(self):
  _,off_a,_=self.call('POST','/api/officers',{'name':'Officer A','role':'Detective','badge':'OPS-A'},self.admin)
  _,off_b,_=self.call('POST','/api/officers',{'name':'Officer B','role':'Detective','badge':'OPS-B'},self.admin)
  start=(date.today()-timedelta(days=10)).isoformat()
  for ref,officer in [('OPS-A-1','Officer A'),('OPS-A-2','Officer A'),('OPS-B-1','Officer B')]:
   self.assertEqual(self.call('POST','/api/cases',{'id':ref,'title':ref,'category':'Test','status':'Active','officer':officer,'date':start},self.admin)[0],201)
  self.assertEqual(self.call('POST','/api/cases',{'id':'OPS-ASSIGN','title':'Least load assignment','category':'Test','status':'Active','date':start},self.admin)[0],201)
  status,assigned,_=self.call('POST','/api/cases/OPS-ASSIGN/assign',cookie=self.admin);self.assertEqual(status,200);self.assertEqual(assigned['assigned_officer'],'Officer B')
  denied=self.call('POST','/api/cases/OPS-A-1/assign',cookie=self.operator);self.assertEqual(denied[0],403)
  status,closed,_=self.call('POST','/api/cases/OPS-ASSIGN/close',{'resolution':'Fictional demo resolution'},self.admin);self.assertEqual(status,200);self.assertEqual(closed['item']['resolution'],'Fictional demo resolution');self.assertEqual(closed['item']['status'],'Closed')
  self.assertEqual(self.call('POST','/api/cases/OPS-A-1/close',{'resolution':'Not authorized'},self.operator)[0],403)
  history=self.call('GET','/api/cases/OPS-ASSIGN/history',cookie=self.admin)[1];self.assertTrue(any(event['type']=='status' and event['new_status']=='Closed' for event in history['items']))
  report=self.call('GET','/api/reports',cookie=self.admin)[1];aged=next(item for item in report['case_aging'] if item['case_reference']=='OPS-A-1');self.assertGreaterEqual(aged['days_open'],9)
  status,officers=self.call('GET','/api/officers',cookie=self.admin)[:2];by_badge={item['badge']:item for item in officers['items']};self.assertEqual(status,200)
  transfer_path=f"/api/officers/{by_badge['OPS-B']['id']}/transfer-cases"
  status,moved,_=self.call('POST',transfer_path,{'to_badge':'OPS-A'},self.admin);self.assertEqual(status,200);self.assertEqual(moved['moved'],2)
  self.assertEqual(self.call('POST',transfer_path,{'to_badge':'OPS-A'},self.operator)[0],403)

 def test_transfer_failure_rolls_back_cases_audit_and_activity(self):
  _,source,_=self.call('POST','/api/officers',{'name':'Rollback Source','role':'Detective','badge':'ROLL-SRC'},self.admin)
  _,target,_=self.call('POST','/api/officers',{'name':'Rollback Target','role':'Detective','badge':'ROLL-DST'},self.admin)
  for ref in ('ROLL-1','ROLL-2','ROLL-3'):
   self.call('POST','/api/cases',{'id':ref,'title':ref,'category':'Test','status':'Active','officer':'Rollback Source'},self.admin)
  conn=api.connect();cur=conn.cursor();cur.execute("SELECT COUNT(*) n FROM audit_log WHERE table_name='cases' AND action='UPDATE'");audit_before=api.one_dict(cur)['n'];cur.execute("SELECT COUNT(*) n FROM activity WHERE action='transferred'");activity_before=api.one_dict(cur)['n']
  with self.assertRaisesRegex(RuntimeError,'Injected mid-transfer failure'):
   api.service_transfer_cases(conn,'ROLL-SRC','ROLL-DST',{'username':'manager'},fail_after=2)
  cur.execute('SELECT officer_id,COUNT(*) n FROM cases WHERE case_ref LIKE ? GROUP BY officer_id',('ROLL-%',));assigned={row['officer_id']:row['n'] for row in api.cursor_dicts(cur)}
  cur.execute("SELECT COUNT(*) n FROM audit_log WHERE table_name='cases' AND action='UPDATE'");audit_after=api.one_dict(cur)['n'];cur.execute("SELECT COUNT(*) n FROM activity WHERE action='transferred'");activity_after=api.one_dict(cur)['n'];conn.close()
  self.assertEqual(assigned,{source['item']['id']:3});self.assertEqual(audit_after,audit_before);self.assertEqual(activity_after,activity_before)

if __name__=='__main__':unittest.main()
