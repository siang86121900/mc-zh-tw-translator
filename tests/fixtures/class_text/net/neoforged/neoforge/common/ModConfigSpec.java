package net.neoforged.neoforge.common;
public class ModConfigSpec {
    public static class Builder {
        public Builder comment(String text) { return this; }
        public Builder comment(String... text) { return this; }
        public Builder define(String key, boolean value) { return this; }
    }
}
