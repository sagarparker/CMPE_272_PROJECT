package com.mediamesh.storage;

import com.azure.core.http.jdk.httpclient.JdkHttpClientBuilder;
import com.azure.core.util.Context;
import com.azure.identity.ManagedIdentityCredentialBuilder;
import com.azure.storage.blob.*;
import com.azure.storage.blob.models.*;
import com.azure.storage.blob.sas.*;
import com.azure.storage.common.policy.*;
import com.azure.storage.common.sas.SasProtocol;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Map;

@Component
public class AzureBlobStorage implements MediaStorage {
    private static final Duration DEADLINE = Duration.ofSeconds(10);
    private final BlobServiceClient service;
    private final BlobContainerClient container;
    private final long maxBytes;
    private UserDelegationKey key;
    private final String publicEndpoint;

    @Autowired
    public AzureBlobStorage(@Value("${AZURE_STORAGE_ACCOUNT:}") String account,
            @Value("${AZURE_STORAGE_CONTAINER:mediamesh}") String containerName,
            @Value("${mediamesh.storage.max-upload-bytes}") long maxBytes,
            @Value("${AZURE_EMULATOR_ENDPOINT:}") String emulatorEndpoint,
            @Value("${AZURE_STORAGE_PUBLIC_ENDPOINT:http://localhost:10000/devstoreaccount1}") String publicEndpoint) {
        this(emulatorEndpoint.isBlank() ? client(account) : LocalBlobEmulator.client(emulatorEndpoint),
                containerName, maxBytes, emulatorEndpoint.isBlank() ? null : LocalBlobEmulator.publicEndpoint(publicEndpoint));
    }

    AzureBlobStorage(String account, String containerName, long maxBytes) {
        this(client(account), containerName, maxBytes);
    }

    private static BlobServiceClient client(String account) {
        if (!account.matches("[a-z0-9]{3,24}")) throw new IllegalArgumentException("Invalid Azure storage account");
        var http = new JdkHttpClientBuilder().connectionTimeout(Duration.ofSeconds(3))
                .readTimeout(Duration.ofSeconds(5)).writeTimeout(Duration.ofSeconds(5)).responseTimeout(DEADLINE).build();
        return new BlobServiceClientBuilder().endpoint("https://"+account+".blob.core.windows.net")
                .credential(new ManagedIdentityCredentialBuilder().httpClient(http).build())
                .httpClient(http).retryOptions(new RequestRetryOptions(RetryPolicyType.FIXED,2,3,200L,500L,null))
                .buildClient();
    }

    AzureBlobStorage(BlobServiceClient service, String containerName, long maxBytes) {
        this(service,containerName,maxBytes,null);
    }

    AzureBlobStorage(BlobServiceClient service, String containerName, long maxBytes, String publicEndpoint) {
        this.service=service; this.container=service.getBlobContainerClient(containerName); this.maxBytes=maxBytes;
        this.publicEndpoint=publicEndpoint;
    }

    private synchronized UserDelegationKey signingKey() {
        var now=OffsetDateTime.now();
        if (key==null || key.getSignedExpiry().isBefore(now.plusMinutes(20)))
            key=service.getUserDelegationKeyWithResponse(now.minusMinutes(5),now.plusHours(1),DEADLINE,Context.NONE).getValue();
        return key;
    }

    @Override public Map<String,String> uploadHeaders() { return Map.of("x-ms-blob-type","BlockBlob"); }

    @Override public String createUploadUrl(String objectKey, String contentType) {
        // Create-only SAS cannot overwrite an existing blob, even if a client omits If-None-Match.
        return signed(objectKey,new BlobSasPermission().setCreatePermission(true),900,null);
    }

    @Override public String createAccessUrl(String objectKey, boolean download) {
        return signed(objectKey,new BlobSasPermission().setReadPermission(true),60,download?"attachment":"inline");
    }

    private String signed(String objectKey, BlobSasPermission permission, long seconds, String disposition) {
        if (!objectKey.startsWith("assets/")) throw new IllegalArgumentException("Expected catalog object key");
        var blob=container.getBlobClient(objectKey);
        var values=new BlobServiceSasSignatureValues(OffsetDateTime.now().plusSeconds(seconds),permission)
                .setProtocol(publicEndpoint==null?SasProtocol.HTTPS_ONLY:SasProtocol.HTTPS_HTTP).setStartTime(OffsetDateTime.now().minusMinutes(5));
        if(disposition!=null) values.setContentDisposition(disposition);
        if(publicEndpoint!=null) {
            String path=blob.getBlobUrl().substring(service.getAccountUrl().replaceAll("/$", "").length());
            return publicEndpoint+path+"?"+blob.generateSas(values);
        }
        return blob.getBlobUrl()+"?"+blob.generateUserDelegationSas(values,signingKey());
    }

    @Override public void verifyUpload(String objectKey, String mediaType) {
        try {
            var properties=container.getBlobClient(objectKey).getPropertiesWithResponse(null,DEADLINE,Context.NONE).getValue();
            if(properties.getBlobSize()<=0 || properties.getBlobSize()>maxBytes)
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Uploaded media is empty or exceeds the size limit");
            String type=properties.getContentType();
            boolean valid="image".equals(mediaType)?"image/jpeg".equals(type)||"image/png".equals(type)
                    :"video".equals(mediaType)&&("video/mp4".equals(type)||"video/quicktime".equals(type));
            if(!valid) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Uploaded content type does not match media type");
        } catch(BlobStorageException error) {
            if(error.getStatusCode()==404) throw new ResponseStatusException(HttpStatus.CONFLICT,"Uploaded object was not found");
            throw error;
        }
    }
}
