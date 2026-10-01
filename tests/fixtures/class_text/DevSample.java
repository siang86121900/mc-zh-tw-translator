import org.slf4j.Logger;
import net.minecraft.network.chat.Component;

public class DevSample {
    static Logger LOG;
    static void run(Object value) {
        LOG.info("Loaded the config file from disk");
        LOG.warn("Could not parse the entry {}", value);
        if (value == null) throw new IllegalStateException("Registry object was not present here");
        LOG.info("Welcome back to the world");
        Component.literal("Welcome back to the world");
        Component.literal("Shown to every single player");
    }
}
