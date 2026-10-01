package net.neoforged.neoforge.common.data;

/** Stand-in for NeoForge's data generator of language files. */
public abstract class LanguageProvider {
    protected abstract void addTranslations();
    protected void add(String key, String value) {}
}
