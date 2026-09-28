import json,re,zipfile,shutil
from pathlib import Path
from full_translation_audit import parse,placeholders,fingerprint
from mc_zh_tw_translator.translator import ReferencePackDB,is_jar_signature_file
root=Path(__file__).resolve().parents[1]
base=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
p=base/'mods/PatPat-1.2.2+1.20.1.jar'
name='assets/patpat/lang/zh_tw.json';enname=name.replace('zh_tw','en_us')
reviewed=json.loads((root/'data/patpat_reviewed_zh_tw.json').read_text(encoding='utf-8'))
db=ReferencePackDB(root/'data');db.load_all();db.set_namespace('patpat')
with zipfile.ZipFile(p) as z:
    en=parse(z.read(enname));cn=parse(z.read(name.replace('zh_tw','zh_cn')))
    assert set(en)==set(reviewed),(set(en)-set(reviewed),set(reviewed)-set(en))
    for k,v in reviewed.items():
        assert placeholders(en[k])==placeholders(v),k
        assert sorted(re.findall(r'\{\d+\}',en[k]))==sorted(re.findall(r'\{\d+\}',v)),k
        assert en[k].count('\n')==v.count('\n'),k
    # All supplied Chinese sources were checked before the manual translation.
    chinese_sources={k:cn.get(k) or db.lookup(k) for k in en if re.search('[\u3400-\u9fff]',str(cn.get(k) or db.lookup(k) or ''))}
    print('Chinese sources available:',len(chinese_sources))
    backup=root/'output/VEFV2.7.1_full_audit_backup/mods'/p.name
    if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,backup)
    temp=p.with_suffix('.reviewed.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            if is_jar_signature_file(info.filename):continue
            w.writestr(info,json.dumps(reviewed,ensure_ascii=False,indent=2).encode() if info.filename==name else z.read(info.filename))
temp.replace(p)
decisions={}
for k,v in reviewed.items():
    row=dict(source='mods/'+p.name+'!/'+enname,key=k,en=en[k],current=v,zh_cn=cn.get(k))
    decisions[fingerprint(row)]={'status':'keep_original' if k=='patpat.title' else 'reviewed','reason':'已逐筆對照本版本英文，保留模組名稱及參數；檢查台灣繁中、完整句意與原始換行。'}
(root/'output/VEFV2.7.1_full_audit/decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2),encoding='utf-8')
print('PatPat reviewed and installed:',len(reviewed))
