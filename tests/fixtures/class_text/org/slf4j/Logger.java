package org.slf4j;
public interface Logger {
    void info(String message);
    void warn(String message, Object argument);
}
