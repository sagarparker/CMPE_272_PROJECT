package com.mediamesh.observability;

import ch.qos.logback.classic.spi.*;
import ch.qos.logback.core.encoder.EncoderBase;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.LinkedHashMap;

public class JsonLogEncoder extends EncoderBase<ILoggingEvent> {
    private final ObjectMapper json=new ObjectMapper();
    @Override public byte[] headerBytes(){return null;}
    @Override public byte[] footerBytes(){return null;}
    @Override public byte[] encode(ILoggingEvent event){
        var fields=new LinkedHashMap<String,Object>();
        fields.put("timestamp",Instant.ofEpochMilli(event.getTimeStamp()).toString());
        fields.put("level",event.getLevel().toString());fields.put("logger",event.getLoggerName());
        fields.put("requestId",event.getMDCPropertyMap().getOrDefault("requestId","system"));
        fields.put("message",event.getFormattedMessage());
        if(event.getThrowableProxy()!=null) fields.put("exception",ThrowableProxyUtil.asString(event.getThrowableProxy()));
        try{return (json.writeValueAsString(fields)+"\n").getBytes(StandardCharsets.UTF_8);}
        catch(Exception e){return "{\"level\":\"ERROR\",\"requestId\":\"system\",\"message\":\"Log encoding failed\"}\n".getBytes(StandardCharsets.UTF_8);}
    }
}
