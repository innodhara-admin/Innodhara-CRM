package com.yuvipep.app.feature.assistant.voice;

import androidx.annotation.NonNull;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * The sentences read aloud into the speech test recorder (debug builds only),
 * and the WAV wrapping of what was recorded.
 *
 * <p>Words in [brackets] are the names being scored — client names, people,
 * cities. The bracketed text is the single source of truth: it is written to
 * the recording's manifest line, and the server-side evaluation derives both
 * the reference transcript and the names to check from it.
 */
public final class SpeechEvalPrompts {

    public static final class Prompt {
        @NonNull public final String id;
        /** With [brackets] around the scored names. */
        @NonNull public final String marked;

        Prompt(@NonNull String id, @NonNull String marked) {
            this.id = id;
            this.marked = marked;
        }

        /** What the person reads: the sentence without brackets. */
        @NonNull
        public String display() {
            return marked.replace("[", "").replace("]", "");
        }
    }

    public static final List<Prompt> ALL = Collections.unmodifiableList(Arrays.asList(
            // Creating a client
            p("L01", "Create a lead named [Bal Bhavan Public School]."),
            p("L02", "Create a lead named [Shree Vidya Mandir] in [Pune]."),
            p("L03", "Add a new client called [Orchid International School] in [Bengaluru]."),
            p("L04", "Create a lead for [Sai Krishna Engineering College] in [Hubballi]."),
            p("L05", "New lead, [Greenwood High], in [Mysuru], source referral."),
            p("L06", "Create a client named [Vidyanikethan Public School] in [Tumakuru]."),
            p("L07", "Add [Kendriya Vidyalaya Hebbal] as a lead."),
            p("L08", "Create a lead named [Deshpande Foundation] in [Belagavi]."),
            p("L09", "Create a lead named [Mahalakshmi Textiles] in [Coimbatore]."),
            p("L10", "Add a new lead called [Bhagyashree Hospitals] in [Nashik]."),
            p("L11", "Create a lead named [Sri Chaitanya Techno School] in [Vijayawada]."),
            p("L12", "Create a lead named [Ramaiah Institute of Technology]."),
            p("L13", "Create a lead named [Zenith Motors] in [Mangaluru], I'll own it."),
            p("L14", "Create a lead named [Anand Rathi Securities] in [Indore]."),
            p("L15", "Add a client called [Kalinga Public School] in [Bhubaneswar]."),
            // Choosing the owner
            p("O01", "Give it to [Ria Nair]."),
            p("O02", "[Priya Nair]."),
            p("O03", "[Rahul Verma] should own it."),
            p("O04", "Make [Akash Rathore] the owner."),
            p("O05", "Assign it to [Ananya Iyer]."),
            p("O06", "[Asha Rao]."),
            p("O07", "Let [Meera Joshi] own it."),
            p("O08", "Me."),
            p("O09", "I'll own it myself."),
            // Details
            p("F01", "Add city as [Pune]."),
            p("F02", "The city is [Thiruvananthapuram]."),
            p("F03", "City [Davangere]."),
            p("F04", "The source is a referral from [Kavitha Shenoy]."),
            p("F05", "The website is [greenwood high] dot in."),
            p("F06", "We met their principal, [Anita Deshpande]."),
            p("F07", "The contact is [Venkatesh Gowda], he is the admin officer."),
            p("F08", "Add a note that they want a demo in November."),
            p("F09", "The city is [Hosur], and the source is a trade fair."),
            // Short replies
            p("S01", "Yes."),
            p("S02", "No."),
            p("S03", "Okay."),
            p("S04", "Skip this."),
            p("S05", "Create it."),
            p("S06", "Cancel."),
            p("S07", "No thanks."),
            p("S08", "Go ahead."),
            p("S09", "Someone else."),
            p("S10", "Do whatever you want."),
            p("S11", "That's all."),
            p("S12", "Yes, go ahead."),
            p("S13", "Never mind."),
            p("S14", "You decide."),
            // Spelling
            p("P01", "The second word is [B H A V A N]."),
            p("P02", "The city is [P U N E]."),
            p("P03", "The first word is [S H R E E]."),
            p("P04", "Can you spell the organisation name?"),
            p("P05", "The second word should be [Bhawan] with a W."),
            // Everyday requests
            p("G01", "What are my open tasks today?"),
            p("G02", "Show me the leads in cold calling."),
            p("G03", "Schedule a demo with [Greenwood High] tomorrow at eleven."),
            p("G04", "Draft a follow up email to [Orchid International School] about the proposal."),
            p("G05", "When is my next meeting with [Deshpande Foundation]?"),
            p("G06", "Move [Bal Bhavan Public School] to the demo stage."),
            // Hindi / Kannada mixed (names scored; word error rate not)
            p("H01", "[Priya] ko de do."),
            p("H02", "City [Pune] hai."),
            p("H03", "Haan, bana do."),
            p("H04", "Houdu, maadi."),
            p("H05", "[Rahul] ko owner bana do.")
    ));

    private SpeechEvalPrompts() {
    }

    private static Prompt p(String id, String marked) {
        return new Prompt(id, marked);
    }

    /** 16 kHz mono 16-bit PCM wrapped as a WAV file. */
    @NonNull
    public static byte[] wav(@NonNull byte[] pcm, int sampleRate) {
        ByteBuffer header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        header.put(new byte[]{'R', 'I', 'F', 'F'});
        header.putInt(36 + pcm.length);
        header.put(new byte[]{'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
        header.putInt(16);
        header.putShort((short) 1);          // PCM
        header.putShort((short) 1);          // mono
        header.putInt(sampleRate);
        header.putInt(sampleRate * 2);       // byte rate
        header.putShort((short) 2);          // block align
        header.putShort((short) 16);         // bits per sample
        header.put(new byte[]{'d', 'a', 't', 'a'});
        header.putInt(pcm.length);
        ByteArrayOutputStream out = new ByteArrayOutputStream(44 + pcm.length);
        out.write(header.array(), 0, 44);
        out.write(pcm, 0, pcm.length);
        return out.toByteArray();
    }
}
