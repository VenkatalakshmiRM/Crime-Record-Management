"""Import an explicitly exported legacy browser JSON backup. Existing records are never overwritten."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import api

def import_file(filename):
 data=json.loads(Path(filename).read_text(encoding='utf-8'))
 if not isinstance(data,dict):raise ValueError('Input must be a JSON object with cases, persons, and officers arrays.')
 for key in ('cases','persons','officers'):
  if key in data and not isinstance(data[key],list):raise ValueError(f'{key} must be an array.')
 conn=api.connect();summary={'officers_added':0,'cases_added':0,'persons_added':0,'skipped':0}
 try:
  cur=conn.cursor()
  for o in data.get('officers',[]):
   name=str(o.get('name','')).strip();role=str(o.get('role','')).strip();badge=str(o.get('badge','')).strip()
   if not all((name,role,badge)):summary['skipped']+=1;continue
   cur.execute(api.sql('SELECT id FROM officers WHERE badge=?'),(badge,))
   if api.one_dict(cur):summary['skipped']+=1;continue
   now=api.utcnow();cur.execute(api.sql('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)'),(name,role,badge,now,now));summary['officers_added']+=1
  for c in data.get('cases',[]):
   ref=str(c.get('id','')).strip();title=str(c.get('title','')).strip();category=str(c.get('category','Other')).strip() or 'Other';status=str(c.get('status','Under review')).strip();date=str(c.get('date','')).strip() or None;location=str(c.get('location','')).strip();officer=str(c.get('officer','')).strip()
   if not ref or not title or status not in api.CASE_STATUS or (date and not __import__('re').fullmatch(r'\d{4}-\d{2}-\d{2}',date)):
    summary['skipped']+=1;continue
   if date:
    try:__import__('datetime').date.fromisoformat(date)
    except ValueError:summary['skipped']+=1;continue
   cur.execute(api.sql('SELECT id FROM cases WHERE case_ref=?'),(ref,))
   if api.one_dict(cur):summary['skipped']+=1;continue
   oid=None
   if officer:
    cur.execute(api.sql('SELECT id FROM officers WHERE name=? OR badge=?'),(officer,officer));row=api.one_dict(cur);oid=row['id'] if row else None
   now=api.utcnow();cur.execute(api.sql('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)'),(ref,title,category,status,oid,date,location,now,now));summary['cases_added']+=1
  for person in data.get('persons',[]):
   name=str(person.get('name','')).strip();status=str(person.get('status','Unknown')).strip();charge=str(person.get('charge','')).strip();ref=str(person.get('case','')).strip();age=person.get('age')
   if not name or not charge or status not in api.PERSON_STATUS:summary['skipped']+=1;continue
   cur.execute(api.sql('SELECT id FROM cases WHERE case_ref=?'),(ref,)) if ref else None;linked=api.one_dict(cur) if ref else None
   if ref and not linked:summary['skipped']+=1;continue
   cur.execute(api.sql('SELECT id FROM persons WHERE name=? AND case_id '+('<=>' if __import__('os').environ.get('CASEWORK_DB','sqlite').lower()=='mysql' else 'IS')+' ? AND charge=?'),(name,linked['id'] if linked else None,charge))
   if api.one_dict(cur):summary['skipped']+=1;continue
   try:age=int(age) if age not in (None,'','—') else None
   except (TypeError,ValueError):summary['skipped']+=1;continue
   if age is not None and not 0<=age<=120:summary['skipped']+=1;continue
   now=api.utcnow();cur.execute(api.sql('INSERT INTO persons(name,case_id,age,status,charge,created_at,updated_at) VALUES(?,?,?,?,?,?,?)'),(name,linked['id'] if linked else None,age,status,charge,now,now));summary['persons_added']+=1
  conn.commit();return summary
 except Exception:conn.rollback();raise
 finally:conn.close()
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('json_backup');a=p.parse_args()
 try:print(json.dumps(import_file(a.json_backup),indent=2))
 except Exception as e:raise SystemExit(f'Import stopped without committing changes: {e}')
