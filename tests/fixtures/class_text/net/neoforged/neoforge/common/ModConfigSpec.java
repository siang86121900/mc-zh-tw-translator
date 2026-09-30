package net.neoforged.neoforge.common;
public class ModConfigSpec {
    public static class Builder {
        public Builder comment(String text) { return this; }
        public Builder comment(String... text) { return this; }
        public Builder translation(String key) { return this; }
        public Builder worldRestart() { return this; }
        public Builder push(String name) { return this; }
        public Builder pop() { return this; }
        public Builder define(String key, boolean value) { return this; }
        public Builder defineInRange(String key, double value, double min, double max) { return this; }
    }
}
