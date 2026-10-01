import java.util.ArrayList;
import java.util.List;

/** Like Age of Mythology's ParallelPlayerProfessionCatalog: names kept in a list and shown elsewhere. */
public class NameCatalog {
    static final List<String> NAMES = new ArrayList<>();
    static {
        NAMES.add("巫法师");
        NAMES.add("战士");
    }
    static boolean isWarrior(String name) {
        return "战士".equals(name);
    }
}
