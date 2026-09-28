from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from pathlib import Path


FIXES = {
    "animal_pen-forge-1.20-1.6.1.jar": {
        "display.animal_pen.pollen_level": "%1$s §e花粉：%2$d / §25",
        "display.animal_pen.pollen_level_max": "%1$s §2最大花粉：%2$d",
    },
    "apocalypsenow-3.0.4NS-forge-1.20.1.jar": {
        "entity.apocalypsenow.dropbox": "空投箱",
        "entity.apocalypsenow.medicaldropbox": "醫療空投箱",
        "entity.apocalypsenow.militarydrop": "軍用空投箱",
    },
    "BetterCompatibilityChecker-forge-4.0.8+mc1.20.1.jar": {
        "bcc.gui.tooltip.compatible_server": "§3伺服器版本：{0}\n§2用戶端版本（你）：{1}",
        "bcc.gui.tooltip.incompatible_server": "§6你的整合包版本與伺服器不同 :(\n \n§4伺服器版本：{0}\n§4用戶端版本（你）：{1}",
    },
    "BiomesOPlenty-forge-1.20.1-19.0.0.96.jar": {
        "item.biomesoplenty.liquid_null_bucket": "虛空桶",
        "block.biomesoplenty.liquid_null": "虛空流體",
        "block.biomesoplenty.null_block": "虛空方塊",
        "block.biomesoplenty.null_leaves": "虛空樹葉",
        "block.biomesoplenty.null_plant": "虛空植株",
    },
    "CraftPresence-2.7.0+1.20.1-forge.jar": {
        "craftpresence.command.current_data": "§l目前 RPC 資料（以 %1$s 身分登入）：§r\\n §6§l活動類型：§r %2$s\\n §6§l詳細資料：§r %3$s\\n §6§l遊戲狀態：§r %4$s\\n §6§l開始時間戳：§r %5$s\\n §6§l用戶端 ID：§r %6$s\\n §6§l大圖示鍵：§r %7$s\\n §6§l大圖示文字：§r %8$s\\n §6§l小圖示鍵：§r %9$s\\n §6§l小圖示文字：§r %10$s\\n §6§l隊伍 ID：§r %11$s\\n §6§l隊伍人數：§r %12$s\\n §6§l隊伍人數上限：§r %13$s\\n §6§l隊伍隱私：§r %14$s\\n §6§l加入密鑰：§r %15$s\\n §6§l結束時間戳：§r %16$s\\n §6§l配對密鑰：§r %17$s\\n §6§l旁觀密鑰：§r %18$s\\n §6§l按鈕：§r %19$s\\n §6§l是否為實例：§r %20$s",
        "craftpresence.command.usage.main": "§lCraftPresence－子命令：\\n §r語法：§6/<cp|craftpresence> <command>\\n\\n §6§lreboot §r- 重新啟動 RPC\\n §6§lshutdown §r- 關閉 RPC\\n §6§lcompile §r- 使用 Starscript 測試佔位符運算式的輸出\\n §6§lsearch §r- 搜尋 Rich Presence 可用的有效佔位符\\n §6§lreload §r- 依設定重新載入 CraftPresence 資料\\n §6§lrequest §r- 查看加入請求資訊\\n §6§lexport §r- 查看模組資料匯出指令\\n §6§lview §r- 查看各類顯示資料\\n §6§lhelp §r- 查看本頁",
        "gui.config.comment.display.dynamic_variables": "自訂要在 RPC 中顯示的動態佔位符\\n 注意：\\n - 可使用其他模組的任何佔位符（全域、生態域、維度等）\\n - 可透過「custom.<name>」定義",
    },
    "CustomNPCs-1.20.1-GBPort-Unofficial-20251031.jar": {
        "item.customnpcs.npcmobcloner": "生物複製器",
        "clone.overwrite": "即將覆寫複製資料",
        "spawner.clones": "複製體",
        "guard.creepers": "攻擊苦力怕",
    },
    "createbigcannons-5.9.1-mc.1.20.1-forge.jar": {
        "item.createbigcannons.wired_fuze.tooltip": "接線引信",
    },
    "crittersandcompanions-forge-1.20.1-2.3.5.jar": {
        "entity.crittersandcompanions.shima_enaga": "銀喉長尾山雀",
    },
    "enhancedai-2.6.8.jar": {
        "enhancedai.subtitle.angry_creeper_fuse": "憤怒的苦力怕即將爆炸",
        "enhancedai.subtitle.angry_creeper_explode": "憤怒的苦力怕爆炸",
    },
    "ExtremeSoundMuffler-3.49.2-forge-1.20.1.jar": {
        "slider.btn.volume": "音量：%s",
    },
    "ftb-quests-forge-2001.4.16.jar": {
        "ftbquests.reward.blocked": "已封鎖隊伍「%2$s」的 %1$d 個獎勵",
        "ftbquests.reward.this_blocked": "已封鎖隊伍「%1$s」的獎勵",
    },
    "horror_element_mod-1.6.2-forge-1.20.1.jar": {
        "block.horror_element_mod.light_on": "損壞的燈（開啟）",
    },
    "item_scrapper-1.2.9.jar": {
        "tooltip.item_scrapper.scrappable": "⚒ 可拆解",
        "tooltip.item_scrapper.explosion_chance": "⚠ 爆炸機率：%s%%",
        "tooltip.item_scrapper.durability_multiplier": "↔ 使用耐久度倍率",
    },
    "MEED-1.20.1-6.7.jar": {
        "effect.sculkhorde.sculk_infected.description": "使身體感染蟎蟲，並讓屍群蔓延至附近方塊。效果結束時會生成另一隻蟎蟲與一個伏聆質量方塊。",
        "effect.enderzoology.displacement.description": "隨機傳送至附近位置，並有機率生成終界蟎。",
    },
    "MOAdecor BATH 1.20.1.jar": {
        "block.moa_decor_bath.soporteparajabon": "肥皂架",
        "block.moa_decor_bath.esp_ccent": "中央棕色鏡子",
        "block.moa_decor_bath.destapador": "通管器",
        "block.moa_decor_bath.esp_c": "棕色鏡子",
        "block.moa_decor_bath.esp_cder": "右側棕色鏡子",
        "block.moa_decor_bath.esp_cizq": "左側棕色鏡子",
    },
    "plushie_buddies-0.1.6-1.20.1.jar": {
        "block.plushie_buddies.plushie_creeper": "苦力怕絨毛玩偶",
    },
    "refueled-1.20.1-2.4.2.jar": {
        "message.command.set.health.success": "已成功將 %s 的生命值設為 %s",
        "death.attack.refueled.bergentrucked.player.3": "%s 被 %s 的 Bergentrück 輾碎了",
    },
    "simpleplanes-1.20.1-5.3.3.jar": {
        "key.plane_pitch_down.desc": "飛機俯仰向下",
    },
    "spacecatasb-forge-20.14.0.jar": {
        "tooltip.translation.spacecatasb.conditions.description.moonphase.waxingcresent": "盈月眉月",
    },
    "simplylight-1.20.1-1.4.6-build.50.jar": {
        "block.simplylight.illuminant_black_block_on": "反相黑色照明方塊",
    },
    "sophisticatedbackpacks-1.20.1-3.24.10.1404.jar": {
        "commands.sophisticatedbackpacks.template.list.delete.tooltip": "點擊以刪除範本：%s",
    },
    "spore_2.1.5c_1.20.1.jar": {
        "spore.scanner.line.scamper": "生物遭完全侵蝕前的剩餘時間",
    },
    "THEUNDEADREVAMPED_1.9O_1.20.1.jar": {
        "entity.undead_revamp2.sucker": "吸蝕怪",
        "entity.undead_revamp2.bigsucker": "巨型吸蝕怪",
        "item.undead_revamp2.sucker_spawn_egg": "吸蝕怪生成蛋",
        "item.undead_revamp2.bigsucker_spawn_egg": "巨型吸蝕怪生成蛋",
        "subtitles.clogger_roaring": "阻塞者咆哮",
        "subtitles.royalhurts": "皇族英靈：受傷",
        "subtitles.roddies": "撞針體：死亡",
        "subtitles.cloggerexploding": "腐豕：噴濺",
        "subtitles.sugareww": "噁——！",
        "subtitles.parry": "格擋",
        "subtitles.heavyroar": "沉重鬥屍：咆哮",
        "subtitles.stonecrashes": "石塊碎裂",
        "subtitles.rodambience": "撞針體：低吼",
        "subtitles.hunterdying": "循獵魔：死亡",
        "subtitles.royaldies": "皇族英靈：死亡",
        "subtitles.cloggerbleed": "腐豕：濺血",
        "subtitles.heavydies": "沉重鬥屍：死亡",
        "subtitles.rodstep": "撞針體：腳步聲",
        "subtitles.heavyattack": "沉重鬥屍：攻擊",
        "subtitles.heavyhurt": "沉重鬥屍：受傷",
        "subtitles.therodcharg": "撞針體：衝撞",
        "subtitles.cloggerdies": "腐豕：死亡",
        "subtitles.cloggerambiance": "腐豕：哽咽",
        "subtitles.cloggerexplodes": "腐豕：自爆",
    },
    "Zombie Extreme 1.20.1 0.2.6.jar": {
        "item_group.zombie_extreme.zombie_extreme_mobs": "Zombie Extreme：生物",
        "itemGroup.tabzombie_extreme_mobs": "Zombie Extreme：生物",
    },
    "zombieawareness-1.20.1-1.13.1.jar": {
        "zombieawareness.subtitle.investigate": "生物正在查看動靜",
    },
    "ZeroCore2-1.20.1-2.1.47.jar": {
        "zerocore:debugTool.block.tooltip2": "%1$s預設會在伺服器端執行查詢",
    },
}


SIGNATURE = re.compile(r"^META-INF/[^/]+\.(?:SF|RSA|DSA|EC)$", re.I)


def patch_jar(path: Path, fixes: dict[str, str]) -> int:
    replacements: dict[str, bytes] = {}
    changed = 0
    with zipfile.ZipFile(path, "r") as source:
        for name in source.namelist():
            if not name.startswith("assets/") or not name.endswith("/lang/zh_tw.json"):
                continue
            try:
                data = json.loads(source.read(name).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            touched = False
            for key, value in fixes.items():
                if key in data and data[key] != value:
                    data[key] = value
                    touched = True
                    changed += 1
            if touched:
                replacements[name] = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

        if not replacements:
            return 0

        fd, temporary = tempfile.mkstemp(suffix=".jar", dir=path.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w") as output:
                for item in source.infolist():
                    if SIGNATURE.match(item.filename):
                        continue
                    output.writestr(item, replacements.get(item.filename, source.read(item.filename)))
            source.close()
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return changed


def main() -> None:
    root = Path("output/mods")
    changed = sum(patch_jar(root / jar, fixes) for jar, fixes in FIXES.items())
    print(f"Applied {changed} manual zh_tw fixes")


if __name__ == "__main__":
    main()
