import net.neoforged.neoforge.common.ModConfigSpec.Builder;

public class ConfigSample {
    static String name() { return "computed"; }
    public static void build(Builder b) {
        b.comment("Section about food").push("food");
        b.comment("Shows the saturation bar").define("showSaturation", true);
        b.comment("Uses the mod key").translation("sample.config.alpha").worldRestart().defineInRange("alpha", 0.5, 0.0, 1.0);
        b.comment("First line of help", "Second line of help").define("twoLines", false);
        b.comment("Name is not a constant").define(name(), true);
        b.pop();
    }
}
