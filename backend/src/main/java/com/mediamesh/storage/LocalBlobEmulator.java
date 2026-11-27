package com.mediamesh.storage;

import com.azure.storage.blob.BlobServiceClient;
import com.azure.storage.blob.BlobServiceClientBuilder;
import com.azure.storage.blob.BlobServiceVersion;
import com.azure.storage.common.StorageSharedKeyCredential;
import java.net.URI;

/** Microsoft's public Azurite fixture; never accepts a real cloud account key. */
final class LocalBlobEmulator {
    static final String ACCOUNT = "devstoreaccount1";
    static final String KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==";

    static String endpoint(String value, boolean publicUrl) {
        URI uri=URI.create(value);
        boolean loopback="localhost".equals(uri.getHost()) || "127.0.0.1".equals(uri.getHost());
        if(!"http".equals(uri.getScheme()) || !(loopback || (!publicUrl && "azurite".equals(uri.getHost())))
                || !"/devstoreaccount1".equals(uri.getPath()) || uri.getPort()<1
                || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null)
            throw new IllegalArgumentException("Azurite requires a local HTTP endpoint for devstoreaccount1");
        return value;
    }

    static String publicEndpoint(String value) { return endpoint(value,true); }

    static BlobServiceClient client(String value) {
        return new BlobServiceClientBuilder().endpoint(endpoint(value,false))
                .httpClient(new com.azure.core.http.jdk.httpclient.JdkHttpClientBuilder()
                        .connectionTimeout(java.time.Duration.ofSeconds(3))
                        .readTimeout(java.time.Duration.ofSeconds(5)).build())
                .credential(new StorageSharedKeyCredential(ACCOUNT,KEY))
                .serviceVersion(BlobServiceVersion.V2023_11_03).buildClient();
    }
}
