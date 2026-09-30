// Read class structure and Modified UTF-8 using Java itself. Never load or execute mod classes.
// Build with javac --release 8; class_text_check.py embeds the resulting class for bundled JREs.
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public final class ClassTextCheck {
    static String[] utf;
    static void skip(DataInputStream in, long n) throws IOException {
        if (n < 0 || n > in.available()) throw new IOException("Truncated class");
        while (n > 0) { int read = in.skipBytes((int)n); if (read == 0) throw new EOFException(); n -= read; }
    }
    static void attributes(DataInputStream in) throws IOException {
        int count = in.readUnsignedShort();
        for (int i=0;i<count;i++) {
            String name = utf[in.readUnsignedShort()];
            long size = Integer.toUnsignedLong(in.readInt());
            if ("Code".equals(name)) {
                int before = in.available();
                in.readUnsignedShort(); in.readUnsignedShort();
                skip(in, Integer.toUnsignedLong(in.readInt()));
                skip(in, 8L*in.readUnsignedShort()); attributes(in);
                if (before-in.available()!=size) throw new IOException("Code length mismatch");
            } else skip(in,size);
        }
    }
    static void check(Path file) throws IOException {
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(Files.readAllBytes(file)))) {
            if (in.readInt()!=0xcafebabe) throw new IOException("Class magic");
            in.readUnsignedShort(); in.readUnsignedShort();
            int count=in.readUnsignedShort(); utf=new String[count];
            for (int k=1;k<count;k++) {
                switch(in.readUnsignedByte()) {
                    case 1: utf[k]=in.readUTF(); break;
                    case 3: case 4: skip(in,4); break;
                    case 5: case 6: skip(in,8); k++; break;
                    case 7: case 8: case 16: case 19: case 20: skip(in,2); break;
                    case 9: case 10: case 11: case 12: case 17: case 18: skip(in,4); break;
                    case 15: skip(in,3); break;
                    default: throw new IOException("Constant pool tag");
                }
            }
            skip(in,6); skip(in,2L*in.readUnsignedShort());
            for (int group=0;group<2;group++) {
                int members=in.readUnsignedShort();
                for (int i=0;i<members;i++) { skip(in,6); attributes(in); }
            }
            attributes(in);
            if (in.available()!=0) throw new IOException("Trailing class bytes");
        }
    }
    public static void main(String[] args) throws IOException {
        for (String line:Files.readAllLines(Paths.get(args[0]),StandardCharsets.UTF_8)) check(Paths.get(line));
    }
}
