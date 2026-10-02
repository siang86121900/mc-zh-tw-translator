import java.util.List;
import java.util.Map;
import net.minecraft.network.chat.Component;

// Cobblemon Battle Positions 1.1.3 and Cobblemon Additions 4.1.6, reduced: tooltip text handed to a helper that keeps it
// in an anonymous class's field, a "Required"/"Optional" choice, and an English sentence used as the language key.
public class ItemHelp {
    interface Tip { void add(List<Component> out); }
    static final Tip OPPONENT = make("Where opponent's Pokemon spawns", true);
    static final Tip OWN = make("Where your Pokemon spawns", false);
    public static String exposed;
    private static Map<String, String> names;

    private static Tip make(String description, boolean required) {
        return new Tip() {
            public void add(List<Component> out) {
                out.add(Component.literal(description));
                out.add(Component.literal(required ? "Required" : "Optional"));
            }
        };
    }

    // Kept in a public field another mod may read: not proven.
    static void keep() { store("Kept in a public field"); }
    private static void store(String text) { exposed = text; }

    // Handed on and then used to look something up: not proven.
    static String find() { return names.get(pass("Looked up by this name")); }
    private static String pass(String text) { return text; }

    // A method another mod could override: not proven.
    static void open(List<Component> out) { new ItemHelp().show(out, "Shown by a method others can override"); }
    public void show(List<Component> out, String text) { out.add(Component.literal(text)); }

    void spawner(List<Component> out, int offset) {
        out.add(Component.translatable("Spawner: %1$s\nOffset: %2$i", "x", offset));
    }

    static String path() { return "pokemon_spawner"; }
}
