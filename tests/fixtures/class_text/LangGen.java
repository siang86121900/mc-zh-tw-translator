import net.neoforged.neoforge.common.data.LanguageProvider;

/** Like torchesbecomesunlight's ZhCnProvider: writes zh_cn.json when the mod is built. */
public class LangGen extends LanguageProvider {
    @Override
    protected void addTranslations() {
        add("item.sample.meat", "驮兽肉");
        add("item.sample.blade", "纠察队弯刀");
    }
}
