package net.minecraft.network.chat;
public interface Component {
    static MutableComponent literal(String text) { return null; }
    static MutableComponent translatable(String key) { return null; }
    static MutableComponent translatable(String key, Object... args) { return null; }
}
