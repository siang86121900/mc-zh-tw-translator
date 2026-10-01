/** Another class of the same mod: compares a stored name with a literal, which must keep its characters. */
public class NameUser {
    static String title(String name) {
        switch (name) {
            case "巫法师":
                return "法系";
            default:
                return "其他";
        }
    }
}
