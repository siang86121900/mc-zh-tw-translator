import net.neoforged.neoforge.common.ModConfigSpec.Builder;
import net.minecraft.network.chat.Component;

public class Sample {
    private static final String COMMENT = "If true, shows food values while holding SHIFT";
    public static final String PUBLIC = "Public shared string must stay";
    public static void show(Builder b, String incoming) {
        b.comment(COMMENT).define("showFoodValues", true);
        b.comment("First configuration comment", "Second configuration comment");
        Component.literal("Welcome to the world");
        Component.literal("Keep controls \u0001 and emoji \ud83c\udf1f");
        Component.literal(PUBLIC);
        b.comment("Shared with unsafe comparison");
        if (incoming.equals("Shared with unsafe comparison")) System.out.println(incoming);
        b.define("Not a display setting", true);
        System.out.println("This is a log message");
    }
}
