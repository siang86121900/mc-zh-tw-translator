"""Stage explicitly reviewed Fox Ablaze translations and three exact repairs."""
import json, hashlib, shutil, zipfile
from pathlib import Path
from full_translation_audit import placeholders
from mc_zh_tw_translator.translator import is_jar_signature_file

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/'output/Tensura Neo Otherworld/rebuild_review'
SRC=ROOT/'input/Tensura Neo Otherworld/source_20260928'
OUT=B/'reviewed'
CORRECTIONS={
'foxablazeultimate.beelzebub.fluid.extract_hint_lava':'§o手持空桶按右鍵即可取出',
'foxablazeultimate.beelzebub.fluid.extract_hint_water':'§o手持水桶、海綿或玻璃瓶按右鍵即可取出',
'foxablazeultimate.debug.requirements.condition.ender_dragon':'已擊敗終界龍（擊殺紀錄或進度）',
'foxablazeultimate.debug.requirements.condition.max_magicule':'永久魔素上限：%s/%s（取得時會永久扣除設定的數量）',
'foxablazeultimate.debug.requirements.condition.special_race':'符合特殊種族資格（勇者之卵、真勇者、魔王種或真魔王；依設定要求）',
'foxablazeultimate.predation_filter.command.added':'已增加 %s 個捕食過濾欄位給 %s。目前總欄位數：%s（管理員加成：%s）',
'foxablazeultimate.skill.beelzebub.fusion_declaration':'§b§o《告。暴食者與無心者已被識別為同一股更強大的渴望。正在重新統合為更高階的「暴食之王」。虛數空間權能已解鎖。》',
'foxablazeultimate.skill.beelzebub.fusion_message':'§r §c暴食者與無心者已融合為暴食之王·別西卜！',
'foxablazeultimate.skill.fortuna.passive.spatial_damage':'被動：空間傷害變為 6 倍，無法與空間支配疊加。',
'foxablazeultimate.skill.fortuna.passive.warp_shot':'被動（裝備時）：跳躍魔彈。支援的箭矢、苦無、槍械等投射物會傳送到瞄準生物的身後；潛行時不會觸發，每次發射消耗 30 魔素。無法與空間支配疊加。',
'foxablazeultimate.skill.raphael.description':'聆聽萬象之理，於無聲處推演因果，將紛雜之力歸於唯一正解。',
'foxablazeultimate.skill.raphael.fusion_declaration':'§b§o《告。個體輔助權能已提升。思考加速、解析鑑定與並列演算已重新統合。》',
'foxablazeultimate.skill.raphael.fusion_message':'§r §c大賢者與變質者已融合為智慧之王·拉斐爾！',
'foxablazeultimate.skill.shub_niggurath.description':'承載於無數靈魂迴廊中的祈願與可能性，在希耶爾的統合下匯聚為孕育萬般能力的豐穰權能。',
'foxablazeultimate.skill.shub_niggurath.gift.prepared':'已準備贈與 %s。請對準靈魂迴廊目標或命名部下，再次按下技能鍵；潛行時按下技能鍵可取消。',
'item.foxablazeultimate.captured_entity.type':'種類：%s',
}

def digest(b): return hashlib.sha256(b).hexdigest()
def main():
    if OUT.exists(): raise RuntimeError('Reviewed output already exists')
    shutil.copytree(SRC/'mods',OUT/'mods')
    rows=[json.loads(l) for l in (B/'provenance.jsonl').open(encoding='utf-8')]
    selected=[r for r in rows if r.get('namespace')=='foxablazeultimate' and r['file'].startswith('mods/') or r.get('source')=='manual']
    grouped={}
    for r in selected:
        jar,n=r['file'].split('!/',1)
        if r['key'] in CORRECTIONS:
            r['after']=CORRECTIONS[r['key']]; r['source']='manual'
        assert placeholders(r['en'])==placeholders(r['after']),r['key']
        r['reviewed']=True
        r['review_fingerprint']=digest(json.dumps([r['file'],r['key'],r['en'],r['zh_cn'],r['before'],r['after']],ensure_ascii=False).encode())
        grouped.setdefault(jar,{}).setdefault(n,{})[r['key']]=r['after']
    grouped.setdefault('mods/NaturesAura-41.9.jar',{})
    # Empty input language file has no text to translate; add a valid empty counterpart.
    grouped.setdefault('mods/tensuramoreutils-1.8.jar',{})['assets/trstarlight/lang/zh_tw.json']={}
    manifest=[]
    for rel,entries in grouped.items():
        src=SRC/rel; dst=OUT/rel
        with zipfile.ZipFile(src) as z:
            replacements={}
            for n,edits in entries.items():
                data=json.loads(z.read(n).decode('utf-8-sig')) if n in z.namelist() else {}
                data.update(edits)
                replacements[n]=json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
            with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
                seen={}
                for info in z.infolist():
                    content=z.read(info)
                    if info.filename in seen:
                        assert seen[info.filename]==digest(content)
                        continue
                    seen[info.filename]=digest(content)
                    if info.filename not in replacements and not is_jar_signature_file(info.filename):w.writestr(info,content)
                for n,b in replacements.items():w.writestr(n,b)
        with zipfile.ZipFile(src) as z,zipfile.ZipFile(dst) as w:
            for n in set(z.namelist()):
                if n not in replacements and not is_jar_signature_file(n): assert z.read(n)==w.read(n),n
        manifest.append(dict(file=rel,before=digest(src.read_bytes()),after=digest(dst.read_bytes()),resources=list(entries)))
    (B/'reviewed_provenance.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
    (B/'reviewed_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(reviewed_entries=len(selected),files=len(manifest)),ensure_ascii=False))

if __name__=='__main__':main()
