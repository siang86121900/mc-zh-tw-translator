"""Real failure shapes: partly covered files, short labels, changed content and silent read failures."""
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import text_inventory as inv, desktop_jobs as jobs
from mc_zh_tw_translator import codex_bridge as ai
import inventory_text


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'整合包';self.root.mkdir()

    def write(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),encoding='utf-8')
        return p

    def inspect(self,rows=()):
        return inv.reconcile(inv.collect(self.root),rows)

    def row(self,source,key,text,kind='config'):
        return dict(source=source,key=key,en=text,current=None,zh_cn=None,kind=kind)

    def unknown_mod(self,title='Required'):
        p=self.root/'mods/demo.jar';p.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('data/demo/unknown/a.json',json.dumps({'title':title}))
        return p

    def test_partial_file_and_repeated_text_are_checked_by_position(self):
        name='config/quest.json'
        self.write(name,{'title':'Required','pages':[{'text':'Start a Server'},{'text':'Start a Server'}]})
        rows=[self.row(name,'["title"]','Required'),self.row(name,'["pages", 0, "text"]','Start a Server')]
        result=self.inspect(rows)
        missing=[c for c in result['candidates'] if c['state']=='uncovered']
        self.assertEqual([(c['key'],c['text']) for c in missing],[('["pages", 1, "text"]','Start a Server')])

    def test_language_union_requires_each_key_and_original_match(self):
        path='kubejs/assets/demo/lang/'
        self.write(path+'en_us.json',{'a':'Required','b':'Optional'})
        self.write(path+'zh_cn.json',{'a':'必填','only_cn':'缺少的內容'})
        rows=[dict(self.row('instance!/'+path+'en_us.json','a','Required','language'),zh_cn='必填'),
              self.row(path+'en_us.json','b','An older sentence','language')]
        result=self.inspect(rows)
        missing={(c['key'],c['text']) for c in result['candidates'] if c['state']=='uncovered'}
        self.assertEqual(missing,{('b','Optional'),('only_cn','缺少的內容')})

    def test_saved_worlds_ids_comments_other_languages_and_machine_assets_are_untouched(self):
        self.write('saves/world/a.json',{'title':'Saved book'})
        self.write('config/quests-backup/a.json',{'title':'Old task'})
        self.write('resourcepacks/assets/demo/lang/ja_jp.json',{'a':'Required'})
        self.write('resourcepacks/assets/demo/models/a.json',{'name':'Required'})
        self.write('config/a.json',{'name':'minecraft:stone','title':'file.zip','id':'Required','__comment':'Required'})
        self.assertEqual(self.inspect()['candidates'],[])

    def test_whole_book_page_and_inline_language_have_explicit_coverage(self):
        name='resourcepacks/assets/demo/books/en_us/a.txt'
        self.write(name,'Required\nStart a Server')
        self.write(name.replace('/en_us/','/zh_cn/'),'必填\n啟動伺服器')
        self.write('config/inline.json',{'page':{'en_us':'Required','zh_cn':'必填','ja_jp':'Required'}})
        rows=[dict(self.row(name,'text','Required\nStart a Server','book'),zh_cn='必填\n啟動伺服器'),
              dict(self.row('config/inline.json','["page"]','Required','inline_lang'),zh_cn='必填')]
        self.assertTrue(all(c['state']=='covered' for c in self.inspect(rows)['candidates']))

    def test_bad_json_nbt_and_zip_are_recorded_instead_of_clean_result(self):
        self.write('config/bad.json','{"title":')
        self.write('datapacks/bad.nbt','not binary nbt')
        self.write('mods/bad.jar','not a zip')
        result=self.inspect()
        self.assertEqual({e['source'] for e in result['errors']},{'config/bad.json','datapacks/bad.nbt','mods/bad.jar'})
        self.assertIn('未能完成檢查',inv.categories(result))

    def test_nested_archive_and_short_unknown_display_fields_are_detected(self):
        inner=io.BytesIO()
        with zipfile.ZipFile(inner,'w') as z:z.writestr('data/demo/unknown/a.json','{"title":"Required"}')
        p=self.root/'mods/demo.jar';p.parent.mkdir()
        with zipfile.ZipFile(p,'w') as z:z.writestr('libs/inner.jar',inner.getvalue())
        self.assertEqual([(c['source'],c['text']) for c in self.inspect()['candidates']],
                         [('mods/demo.jar!/libs/inner.jar!/data/demo/unknown/a.json','Required')])

    def test_limits_and_cancellation_are_not_reported_as_success(self):
        self.write('config/large.txt','Long enough')
        with patch.object(inv,'MAX_TEXT',3):
            self.assertEqual(len(self.inspect()['errors']),1)
        with self.assertRaises(InterruptedError):inv.collect(self.root,cancelled=lambda:True)

    def test_truncated_nbt_is_an_incomplete_read_not_a_scan_crash(self):
        self.write('datapacks/empty.nbt','')
        self.assertEqual([e['source'] for e in self.inspect()['errors']],['datapacks/empty.nbt'])

    def test_non_player_decision_fingerprint_also_tracks_context_changes(self):
        p=self.write('config/a.json',{'title':'Required','type':'developer'})
        before=self.inspect()['candidates'][0]['fingerprint']
        p.write_text('{"title":"Required","type":"player"}',encoding='utf-8')
        self.assertNotEqual(before,self.inspect()['candidates'][0]['fingerprint'])

    def test_cache_reuses_unchanged_files_but_rechecks_changes_rules_and_read_failures(self):
        p=self.write('config/a.json',{'title':'Required'});cache=self.base/'cache'
        first=inv.collect(self.root,cache=cache)
        with patch.object(inv,'inspect_file',side_effect=AssertionError('unchanged file was parsed twice')):
            second=inv.collect(self.root,cache=cache)
        self.assertEqual(first['candidates'],second['candidates']);self.assertEqual(second['cache_hits'],1)
        p.write_text('{"title":"Optional"}',encoding='utf-8')
        third=inv.collect(self.root,cache=cache);self.assertEqual(third['cache_hits'],0)
        self.assertEqual(third['candidates'][0]['text'],'Optional')
        with patch.object(inv,'RULES_VERSION','next'):
            self.assertEqual(inv.collect(self.root,cache=cache)['cache_hits'],0)
        self.write('config/bad.json','{')
        self.assertTrue(inv.collect(self.root,cache=cache)['errors'])
        self.write('config/bad.json',{'title':'Now readable'})
        self.assertFalse(inv.collect(self.root,cache=cache)['errors'])

    def test_completion_shows_unsupported_reads_and_doubts_without_claiming_full_game_coverage(self):
        session=dict(rows=[self.row('config/a.json','folder','Required','unsupported_config_text'),
                           dict(self.row('mods/demo.jar!/assets/demo/lang/en_us.json','a','Required'),
                                kind='language',supported=True,proposed='必填',origin='ai_translation',number_doubt='數值不同')],
                     text_inventory=dict(errors=[dict(source='config/bad.json')]))
        view=jobs.home_cards(session)
        self.assertIn('尚未支援',view['written']);self.assertIn('沒讀完',view['written'])
        self.assertIn('1 筆具體翻譯疑點',view['written'])
        self.assertIn('不能視為整包翻完',view['warning']);self.assertIn('沒讀完',view['warning'])
        self.assertIn('尚非遊戲畫面實測',view['cards'][0][1])

    def test_content_change_same_counts_and_legacy_summary_require_recheck(self):
        p=self.write('config/a.json',{'title':'Required'})
        before=inv.categories(self.inspect())
        p.write_text('{"title":"Optional"}',encoding='utf-8')
        after=inv.categories(self.inspect())
        self.assertEqual([(v['files'],v['strings']) for v in before.values()],[(v['files'],v['strings']) for v in after.values()])
        self.assertEqual(inv.changed_categories(after,before),after)
        self.assertEqual(inv.changed_categories(after,after),{})
        self.assertEqual(inv.changed_categories(after,{k:{'files':1,'strings':1} for k in after}),after)

    def test_known_unsupported_is_recorded_not_mistaken_for_coverage(self):
        name='config/unknown.json';self.write(name,{'title':'Required'})
        result=self.inspect([self.row(name,'folder','Possible text','unsupported_config_text')])
        self.assertEqual(result['candidates'][0]['state'],'listed')
        self.assertTrue(inv.categories(result))

    def test_data_key_fallback_does_not_cover_same_words_in_unrelated_field(self):
        name='datapacks/data/demo/advancement/a.json'
        self.write(name,{'title':{'translate':'demo.required','fallback':'Required'},'description':'Required'})
        row=dict(self.row('mods/demo.jar!/assets/demo/lang/en_us.json','demo.required','Required','language'),
                 key_from_data=name)
        cs=self.inspect([row])['candidates']
        self.assertEqual([(c['key'],c['state']) for c in cs],
                         [('["title", "fallback"]','covered'),('["description"]','uncovered')])

    def test_function_words_scanned_as_units_are_covered(self):
        # COBBLEVERSE: every .mcfunction line was listed as a gap, scanned rows are keyed [line, n] and book pages keep
        # their SNBT escapes (\\n) in the inventory.
        from mc_zh_tw_translator import embedded_text as et
        name='data/demo/function/book.mcfunction'
        body=('say hi\n'
              'tellraw @a [{"text":" [IMPORTANT]","color":"dark_red"},{"text":" Reopen the world.","color":"gold"}]\n'
              "give @s written_book[written_book_content={pages:['[[\"\",{\"text\":\"Congratulations\",\"bold\":true},\"\\\\n on completing\"]]'],title:\"Kanto Book\",author:\"Professor Oak\"}]\n"
              "data merge entity @s {CustomName:'\"Desert Blaze\"',CustomNameVisible:false}\n")
        (self.root/'datapacks').mkdir()
        with zipfile.ZipFile(self.root/'datapacks/dp.zip','w') as z:z.writestr(name,body)
        source='datapacks/dp.zip!/'+name
        rows=[dict(source=source,key=k,en=None,current=t,zh_cn=None,kind='embedded_text') for k,t in et.units(name,body.encode())
              if t!='Professor Oak']  # the author's unit is left out: it must still show as a gap
        states={c['text']:c['state'] for c in self.inspect(rows)['candidates']}
        self.assertEqual(states.pop('Professor Oak'),'uncovered')
        self.assertTrue(states and set(states.values())=={'covered'},states)

    def test_ids_the_game_matches_are_not_inventoried_and_defined_fallbacks_show_nothing(self):
        # Pixelmon: loot entries name items, advancements match criteria, item modifiers use macro variables.
        name='mods/demo.jar'
        (self.root/'mods').mkdir()
        with zipfile.ZipFile(self.root/name,'w') as z:
            z.writestr('data/demo/loot_table/a.json',json.dumps({'pools':[{'entries':[{'type':'item','name':'crossbow','functions':[
                {'function':'set_name','name':{'text':'Old Bow'}}]}]}]}))
            z.writestr('data/demo/advancement/b.json',json.dumps({'criteria':{'c':{'conditions':{'name':'legendary'}}},
                                                                 'display':{'title':{'text':'Legend Caught'}}}))
            z.writestr('data/demo/item_modifier/c.json',json.dumps([{'amount':{'target':{'name':'$speed'}}}]))
            z.writestr('data/demo/function/d.mcfunction','summon pig ~ ~ ~ {CustomName:\'{"translate":"demo.pig","fallback":"Piglin Alchemist"}\'}\n')
        texts={c['text'] for c in inv.collect(self.root)['candidates']}
        self.assertTrue({'Old Bow','Legend Caught'}<=texts,texts)
        self.assertFalse({'crossbow','legendary','$speed'}&texts)
        fallback=dict(source='mods/demo.jar!/data/demo/function/d.mcfunction',key='1:0',mode='literal',
                      text='{"translate":"demo.pig","fallback":"Piglin Alchemist"}')
        defined=[self.row('mods/demo.jar!/assets/demo/lang/en_us.json','demo.pig','Piglin Alchemist','language')]
        self.assertEqual(inv.reconcile(dict(candidates=[dict(fallback)]),defined)['candidates'][0]['state'],'covered')
        self.assertEqual(inv.reconcile(dict(candidates=[dict(fallback)]),[])['candidates'][0]['state'],'uncovered')
        # Gateways: a name that is a language key only shows no literal words.
        keyed=dict(fallback,text='{"translate":"name.gateways.necrotic_farmer","color":"red"}')
        self.assertEqual(inv.reconcile(dict(candidates=[keyed]),[])['candidates'][0]['state'],'covered')
        # FTB Quests chapter ids are not words.
        self.write('config/ftbquests/quests/chapters/a.snbt','{\n\tid: "469FC2D5B99CD7A1"\n\ttitle: "Into the Deep Caves"\n}\n')
        texts={c['text'] for c in inv.collect(self.root)['candidates'] if c['source'].endswith('a.snbt')}
        self.assertEqual(texts,{'Into the Deep Caves'})

    def test_commands_and_ids_are_not_words_but_sentences_are(self):
        for code in ('summon aether:sun_spirit ~ ~1 ~','pmmo admin @p add magic xp 115000','/curios add hands @s',
                     'give @p diamond','{Potion:"ars_nouveau:mana_regen_potion"}','16x twilightforest:aurora_block',
                     '[wallet_slot]','{image:ftb:textures/fishing1.png width:180}','{chair_pack.geckolib.desc}'):
            self.assertTrue(inv.machine_text(code),code)
        for words in ('give it a try','kill the dragon','use /home to go back','the minecraft:diamond is rare',
                      "You think you can keep up with me? Let's see what you've got",'Welcome to the server'):
            self.assertFalse(inv.machine_text(words),words)

    def test_a_sentence_key_row_covers_every_npc_that_says_it(self):
        # Pixelmon wild trainers share lines; the scan keeps one language row per sentence.
        line="You think you can keep up with me? Let's see what you've got"
        cands=[dict(source=f'mods/p.jar!/data/pixelmon/pixelmon/npc/preset/{n}.json',key=f'["interactions", {i}, "message"]',
                    mode='path',text=line) for n,i in (('a',0),('a',1),('b',0))]
        row=dict(source='mods/p.jar!/assets/pixelmon/lang/en_us.json',key=line,en=line,current=None,kind='language')
        self.assertEqual({c['state'] for c in inv.reconcile(dict(candidates=cands),[row])['candidates']},{'covered'})
        other=dict(cands[0],source='mods/p.jar!/data/other/quests/a.json')  # a format shown as written is not covered by a key
        self.assertEqual(inv.reconcile(dict(candidates=[other]),[row])['candidates'][0]['state'],'uncovered')

    def test_book_lines_with_apostrophes_stay_whole(self):
        # Alex's Caves: "the watcher's perspective" was cut at the apostrophe into a fragment no row could match.
        name='mods/a.jar!/assets/alexscaves/books/en_us/forlorn_hollows/watcher.txt'
        page="    During this possession, from the watcher's perspective, the target cannot move.\n"
        found=[dict(c,source=name) for c in inv.inspect_file(name,page.encode())]
        self.assertEqual([c['text'] for c in found],["During this possession, from the watcher's perspective, the target cannot move."])
        row=dict(source=name,key='text',en=page,current=None,kind='book')
        self.assertEqual({c['state'] for c in inv.reconcile(dict(candidates=found),[row])['candidates']},{'covered'})

    def test_indented_book_lines_match_their_page(self):
        name='mods/a.jar!/assets/alexscaves/books/en_us/abyssal_chasm/chapter.txt'
        page='\n    Welcome to the Abyssal Chasm...\n\n    • Inhabitants\n'
        candidate=dict(source=name,key='2:0',mode='literal',text='Welcome to the Abyssal Chasm...')
        row=dict(source=name,key='text',en=page,current=None,kind='book')
        self.assertEqual(inv.reconcile(dict(candidates=[candidate]),[row])['candidates'][0]['state'],'covered')

    def test_empty_settings_and_json5_are_checked_not_reported_as_unreadable(self):
        self.write('cobblenav/settings/pokefinder.json','')
        self.write('config/yacl.json5','{\n\t// comment\n\tshowHint: true,\n\ttitle: "Welcome to the server everyone"\n}')
        self.write('config/broken.json','{not json')
        result=inv.collect(self.root)
        self.assertEqual([e['source'] for e in result['errors']],['config/broken.json'])  # plain JSON still has to parse
        self.assertIn('Welcome to the server everyone',[c['text'] for c in result['candidates']])

    def test_function_fallbacks_are_covered_by_the_rows_data_keys_make(self):
        # Incendium 5.4.4 has no language file: its tellraw fallbacks become rows keyed by the translate key.
        name='datapacks/data/incendium/function/check.mcfunction'
        self.write(name,'tellraw @s [{"translate":"incendium.system.only_load","fallback":"can only load spectral arrows","color":"gray"}]\n')
        row=dict(self.row('mods/incendium.jar!/assets/incendium/lang/en_us.json','incendium.system.only_load',
                          'can only load spectral arrows','language'),key_from_data=name)
        states=[(c['text'],c['state']) for c in self.inspect([row])['candidates']]
        self.assertIn(('can only load spectral arrows','covered'),states)
        self.assertIn(('can only load spectral arrows','uncovered'),[(c['text'],c['state']) for c in self.inspect([])['candidates']])

    def test_component_with_an_empty_text_and_one_word_matches_its_scanned_piece(self):
        candidate=dict(source='mods/a.jar!/data/x/structure/b.nbt',key='["Book"]',mode='path',
                       text='{"extra": [{"bold": true, "text": "Eternatus"}], "text": ""}')
        def state(rows):
            return inv.reconcile(dict(candidates=[dict(candidate)]),rows)['candidates'][0]['state']
        self.assertEqual(state([dict(source=candidate['source'],key='["Book"]',current='Eternatus',kind='embedded_text')]),'covered')
        self.assertEqual(state([dict(source=candidate['source'],key='["Other"]',current='Eternatus',kind='embedded_text')]),'uncovered')

    def test_fallback_of_a_defined_language_key_is_never_shown(self):
        # Mega Showdown: en_us says 'Free Wi-Fi? No, Just Dynamax', the advancement's fallback adds a full stop.
        name='datapacks/data/demo/advancement/a.json'
        self.write(name,{'title':{'translate':'demo.wifi','fallback':'Free Wi-Fi? No, Just Dynamax.'},
                         'description':{'translate':'demo.undefined','fallback':'Collect every bracelet'}})
        row=self.row('mods/demo.jar!/assets/demo/lang/en_us.json','demo.wifi','Free Wi-Fi? No, Just Dynamax','language')
        cs=self.inspect([row])['candidates']
        self.assertEqual([(c['key'],c['state']) for c in cs],
                         [('["title", "fallback"]','covered'),('["description", "fallback"]','uncovered')])

    def test_engine_model_metadata_and_identifier_literals_do_not_become_player_gaps(self):
        with zipfile.ZipFile(self.root/'pack.zip','w') as z:
            z.writestr('data/cobblemon/showdown.zip',b'not read as game text')
            z.writestr('assets/demo/geo/a.json','{"name":"left arm"}')
            z.writestr('fabric.mod.json','{"name":"Fabric Demo","description":"A mod"}')
            z.writestr('assets/demo/lang/en_us.json','{"a":{"text":"Required","color":"gray"}}')
        self.write('config/a.toml','list=["default","true","demo:chest|true"]')
        result=self.inspect([dict(self.row('pack.zip!/assets/demo/lang/en_us.json','a','unused','language'),
                                  en={'text':'Required','color':'gray'})])
        self.assertFalse(result['errors'])
        self.assertEqual([(c['text'],c['state']) for c in result['candidates']],[('Required','covered')])

    def test_custom_label_maps_and_single_character_display_fragments_are_inventoried(self):
        self.write('config/demo.json',{'headerLabel':'Regional Variation','aspectLabels':{'demo':'Chimera A'},
                                      'parts':[{'text':'E'}],'translationKey':'demo.header'})
        self.assertEqual([c['text'] for c in self.inspect()['candidates']],['Regional Variation','Chimera A','E'])

    def test_one_click_plan_exposes_gaps_but_does_not_send_or_write_them(self):
        p=self.unknown_mod();before=p.read_bytes()
        home=self.base/'app'
        session=jobs.plan(self.root,home,lambda *_:None,references=([{},{}],{'tested':True}))
        row=next(r for r in session['rows'] if r.get('inventory_gap'))
        self.assertFalse(row['supported']);self.assertFalse(row['changed'])
        self.assertEqual(jobs.applicable_count(session),0);self.assertEqual(ai.pending_rows(session),[])
        self.assertIn('unknown/a.json',jobs.unsupported_note(session))
        self.assertTrue((Path(session['report'])/'text-inventory.json.gz').exists())
        self.assertEqual(p.read_bytes(),before)

    def test_cli_gate_fails_until_fingerprinted_non_player_decision_and_invalidates_on_change(self):
        self.unknown_mod()
        args=[str(self.root),'--output',str(self.base/'reports'),'--check']
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(inventory_text.main(args),1)
        result=json.loads((self.base/'reports'/self.root.name/'inventory.json').read_text(encoding='utf-8'))
        decisions=self.base/'decisions.json'
        decisions.write_text(json.dumps({c['fingerprint']:{'status':'not_player_text','reason':'測試用開發者標記'}
                                          for c in result['candidates']}),encoding='utf-8')
        args+=['--decisions',str(decisions)]
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(inventory_text.main(args),0)
        self.unknown_mod('Optional')
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(inventory_text.main(args),1)


class ConcreteDoubtTests(unittest.TestCase):
    def row(self,**extra):
        return dict(dict(source='kubejs/assets/demo/lang/en_us.json',key='a',en='Required',current=None,
                         proposed='必填',origin='ai_translation',supported=True,changed=True,issue=''),**extra)

    def test_sources_and_repairs_do_not_become_doubts_or_manual_confirmation(self):
        rows=[self.row(),self.row(origin='same_source_zh_cn',issue='大陸用語改為台灣用語'),
              self.row(issue='已修正轉換用字'),self.row(unified_from='需要')]
        self.assertFalse(any(jobs.needs_check(r) for r in rows))
        self.assertTrue(all(r['origin']!='manual' for r in rows))
        self.assertEqual(jobs.report_overview(dict(rows=rows))['check'],0)

    def test_real_doubts_are_counted_by_problem_even_for_ai_sources(self):
        rows=[self.row(number_doubt='原文 20，譯文 10'),self.row(name_doubt='留有英文'),
              self.row(origin='stale_reference'),self.row(format_fixed=True),
              self.row(ai_review={'verdict':'rejected'})]
        overview=jobs.report_overview(dict(rows=rows))
        self.assertEqual(overview['check'],5)
        self.assertNotIn('AI 補譯',dict(overview['check_kinds']))
        self.assertIn('數值和原文不同',dict(overview['check_kinds']))
        self.assertFalse(jobs.needs_check(self.row(number_doubt='疑點',review_method='user_confirmed')))


if __name__=='__main__':unittest.main()
