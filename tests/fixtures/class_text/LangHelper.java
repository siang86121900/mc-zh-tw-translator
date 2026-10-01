import java.util.function.BiConsumer;

/** Like Age of Mythology's TarotCompletionTranslations: hands entries to the generator, names no LanguageProvider. */
public class LangHelper {
    static void add(BiConsumer<String, String> out) {
        out.accept("tip.sample.ride", "骑乘驮兽可以穿越沙漠");
        out.accept("tip.sample.short", "驮兽");
        out.accept("tip.sample.other", "只写在程序里的说明文字");
    }
}
