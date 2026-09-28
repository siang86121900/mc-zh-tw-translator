from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
import shutil

OUT=Path('output/pdf');OUT.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('JH','C:/Windows/Fonts/msjh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('JHB','C:/Windows/Fonts/msjhbd.ttc',subfontIndex=0))
W,H=595.28,841.89
FINAL=OUT/'VEFV2.7.1_CurseForge_安裝圖解_雲端下載與10G設定.pdf'
CLOUD='https://drive.google.com/file/d/19jUGRxvd_xEw7xNds-osHaSn4i7Yokx7/view?usp=sharing'
c=canvas.Canvas(str(FINAL),pagesize=(W,H))
c.setTitle('VEFV2.7.1 CurseForge 安裝圖解');c.setAuthor('VEFV2.7.1 分享教學')
BLACK='#18212B';GRAY='#65707C';ORANGE='#F58238';BG='#F3F5F7';DARK='#202329';WHITE='#FFFFFF'
def rect(x,t,w,h,color,r=0,stroke=None):
 c.setFillColor(HexColor(color));c.setStrokeColor(HexColor(stroke or color))
 if r:c.roundRect(x,H-t-h,w,h,r,stroke=bool(stroke),fill=1)
 else:c.rect(x,H-t-h,w,h,stroke=bool(stroke),fill=1)
def text(x,t,s,size=11,color=BLACK,bold=False):
 c.setFont('JHB' if bold else 'JH',size);c.setFillColor(HexColor(color));c.drawString(x,H-t-size,s)
def lines(t,ss,size=11,x=46,color=BLACK,lead=19):
 for s in ss:text(x,t,s,size,color);t+=lead
 return t
def step(t,n,title):
 rect(46,t,27,27,ORANGE,6);text(54,t+3,str(n),15,BLACK,True);text(85,t+1,title,18,BLACK,True)
def header(page,subtitle):
 text(46,29,'VEFV2.7.1  /  CurseForge 安裝圖解',10,GRAY)
 text(46,53,subtitle,24,BLACK,True)
 text(46,800,'Windows 版教學  ·  使用分享者提供的實際操作截圖',8,GRAY)
 text(510,800,f'{page} / 5',9,GRAY)
def panel(t,h,title):
 rect(46,t,503,h,DARK,8);text(62,t+10,title,10,'#C7CDD5');text(458,t+10,'示意圖',9,'#C7CDD5')
def button(x,t,w,label):
 rect(x,t,w,30,ORANGE,4);text(x+12,t+7,label,11,BLACK,True)
def field(t,label,value):
 text(68,t,label,10,'#C7CDD5');rect(205,t-3,320,28,'#363A42',4);text(218,t+2,value,12,WHITE)
def link(t,label,url,size=9):
 text(46,t,label,size,'#285F9D');c.linkURL(url,(46,H-t-size-3,549,H-t+2),relative=0)

ASSETS=Path('data/curseforge_guide');ASSETS.mkdir(parents=True,exist_ok=True)
for name,src in [('library','codex-clipboard-1df1ee63-b46f-49be-9b78-be7ff1dcdad9.png'),('create','codex-clipboard-cdfe81b8-1a0c-48b1-b113-15273c3ae0ee.png'),('folder_menu','codex-clipboard-3536931c-2ded-4164-9498-44813dcfb1fb.png'),('archive','codex-clipboard-1a568c19-b526-418d-8906-39ea61784734.png'),('options_menu','codex-clipboard-7185b878-6fb8-4a92-8bf2-bed72201d903.png'),('memory','codex-clipboard-b1ec5bdd-e9c5-439c-9be6-b67a851e8ecf.png')]:
 dest=ASSETS/(name+'.png')
 if not dest.exists():shutil.copy2(Path('C:/Users/User/AppData/Local/Temp')/src,dest)
def screenshot(name,x,t,width,crop):
 # Preserve the supplied image bytes; use a PDF clipping viewport for legibility.
 im=ImageReader(str(ASSETS/(name+'.png')));iw,ih=im.getSize()
 rx,ry,rw,rh=crop;dw=width/rw;dh=dw*ih/iw;height=dh*rh
 c.saveState();p=c.beginPath();p.rect(x,H-t-height,width,height);c.clipPath(p,stroke=0,fill=0)
 c.drawImage(im,x-rx*dw,H-t-dh+ry*dh,width=dw,height=dh)
 c.restoreState();return height

header(1,'下載 CurseForge 並按創建')
lines(91,['跟著 6 個步驟安裝模組包，最後將記憶體設為約 10G。',
          '適用 Minecraft Java 版；請準備可遊玩的 Minecraft 帳號。'])
step(143,1,'下載並安裝 CurseForge')
lines(179,['開啟下方官方網站，下載 Windows 版並完成安裝。',
           '啟動 CurseForge 後，選擇 Minecraft。'])
link(220,'官方下載  www.curseforge.com/download/app','https://www.curseforge.com/download/app',10)
step(273,2,'在我的模組包按創建')
lines(313,['進入「我的模組包」，按左上角的「＋ 創建」。',
           '下圖是實際介面；建立視窗的填寫方式請看下一頁。'])
screenshot('library',46,377,503,(.04,.07,.49,.38))
text(46,654,'實際截圖局部放大：上方「＋ 創建」是新增設定檔的入口。',10,GRAY)
lines(694,['請為這包模組建立新的設定檔，名稱可填 VEFV2.7.1。',
           'Minecraft 版本與 Forge 版本都要依下一頁設定。'],11)
c.showPage()

header(2,'設定 Minecraft 與 Forge 版本')
lines(104,['模組包名稱：VEFV2.7.1　　Minecraft 版本：1.20.1',
           '模組載入器：Forge　　模組載入器版本：forge-47.4.10'],12,lead=23)
text(46,164,'下圖為尚未設定的畫面，26.2 與 forge-65.1.0 都需要改掉。',11,'#A0430B',True)
screenshot('create',92,199,411,(.165,.095,.565,.68))
lines(708,['先將「Minecraft 版本」改成 1.20.1，再選 Forge 與',
           'forge-47.4.10。填好名稱後按右下角「創建」，等待建立完成。'],11)
c.showPage()

header(3,'下載檔案並找到安裝位置')
step(106,3,'到雲端下載分享的檔案')
lines(145,['點下方連結前往 Google 雲端硬碟，下載分享的模組包。',
           '截圖中的檔名為 VEFV2.7.1_0910.rar；下載後先解壓縮，',
           '找到 mods、config、kubejs 等資料夾所在的那一層。'])
link(214,'點此開啟雲端下載頁面',CLOUD,13)
text(46,238,'若檔案後續更新，請以雲端頁面顯示的檔名為準。',9,GRAY)
step(273,4,'右鍵選擇打開資料夾')
lines(312,['回到「我的模組包」，對剛建立的 VEFV2.7.1 按滑鼠右鍵，',
           '選擇下圖反白的「打開資料夾」。'])
screenshot('folder_menu',166,366,240,(.25,.295,.395,.32))
text(46,720,'這個選項會開啟目前模組包專用的資料夾。',10,GRAY)
lines(743,[
           '保持資料夾視窗開著，並確認 Minecraft 遊戲已關閉。'],10.5)
c.showPage()

header(4,'將雲端檔案貼上取代')
step(106,5,'把分享檔案貼上並取代')
lines(146,['在解壓縮後的內容資料夾，選取分享包提供的資料夾與檔案，',
           '按 Ctrl+C 複製。切到步驟 4 開啟的設定檔資料夾，按 Ctrl+V',
           '貼上。遇到同名檔案時，選擇「取代目的地中的檔案」。'])
screenshot('archive',46,222,503,(0,0,1,.91))
text(46,511,'實際截圖：壓縮檔中的資料夾與檔案，要放進背景的模組包資料夾。',9,GRAY)
text(46,543,'同名檔案 → 選擇取代目的地中的檔案',15,BLACK,True)
lines(581,['位置確認：打開設定檔資料夾，就應直接看到 mods、config 等。',
           '不要把外層 VEFV2.7.1 資料夾整個再貼進去，也不要把所有',
           '內容都塞進 mods。若不是全新設定檔，先備份原本的 saves。'],10.5)
lines(660,['允許資料夾合併，並等待所有檔案複製完成。',
           '接著依下一頁調整此設定檔的記憶體，再啟動遊戲。'],11)
text(46,720,'本頁是完整模組包的安裝流程。若另拿到「中文化補丁」，',10,GRAY)
text(46,740,'請先裝好同版本完整模組包，再依補丁內的說明套用。',10,GRAY)
c.showPage()

header(5,'將此設定檔記憶體設為約 10G')
step(106,6,'設定自訂記憶體分配')
lines(146,['回到 CurseForge，對 VEFV2.7.1 按右鍵，選「設定檔選項」。',
           '在「記憶體設定」選擇「自訂記憶體分配」，',
           '將數值調整為 10000 MB，與右下方截圖相同，最後按右下角「完成」儲存。'])
text(46,221,'先開啟設定檔選項',11,BLACK,True)
text(253,221,'再選自訂記憶體分配',11,BLACK,True)
screenshot('options_menu',46,249,183,(.132,.43,.26,.275))
screenshot('memory',253,249,296,(.005,.02,.855,.51))
text(46,546,'目標數值：10000 MB（約 10G）',16,BLACK,True)
text(46,575,'請使用此設定檔的自訂分配，不要停留在 4096 MB 的共用設定。',10,GRAY)
text(46,612,'完成後啟動遊戲',17,BLACK,True)
lines(643,['回到 CurseForge 按「Play／遊玩」。',
           '若跳出 Minecraft Launcher，登入帳號後再按「開始遊戲」。',
           '若遊戲語言不是繁中，到 Options → Language 選「繁體中文」。'],11)
text(46,709,'開不起來時，先核對版本、資料夾層級與記憶體設定。',10,GRAY)
link(742,'CurseForge 官方建立設定檔說明','https://support.curseforge.com/support/solutions/articles/9000196904',8)
text(46,762,'Forge 版本依本包設定檔確認。文件製作日期 2026/09/10。',8,GRAY)
c.save()
print(FINAL)



