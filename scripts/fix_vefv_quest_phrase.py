from pathlib import Path
p=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1/config/ftbquests/quests/chapters/77FEEFCEF1B0D17B.snbt')
s=p.read_text(encoding='utf-8')
s=s.replace('&c新手禮包and遊玩須知','&c新手禮包與遊玩須知')
p.write_text(s,encoding='utf-8')
print('fixed quest phrase')
