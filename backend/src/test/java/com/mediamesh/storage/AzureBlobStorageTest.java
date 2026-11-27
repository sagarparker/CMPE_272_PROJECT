package com.mediamesh.storage;

import com.azure.core.http.rest.Response;
import com.azure.storage.blob.*;
import com.azure.storage.blob.models.*;
import com.azure.storage.blob.sas.BlobServiceSasSignatureValues;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;
import java.time.OffsetDateTime;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AzureBlobStorageTest {
    @Test void emulatorUsesLocalCreateOnlySasAndCannotAcceptACloudEndpoint() {
        var storage=new AzureBlobStorage("", "media",100,
                "http://azurite:10000/devstoreaccount1","http://localhost:10000/devstoreaccount1");
        var upload=java.net.URI.create(storage.createUploadUrl("assets/owner/photo.jpg","image/jpeg"));
        assertEquals("localhost",upload.getHost());
        assertEquals("/devstoreaccount1/media/assets/owner/photo.jpg",upload.getPath());
        assertTrue(upload.getQuery().contains("sp=c&"));
        assertTrue(storage.createAccessUrl("assets/owner/photo.jpg",false).contains("sp=r&"));
        assertThrows(IllegalArgumentException.class,()->LocalBlobEmulator.client("http://storage.blob.core.windows.net:10000/devstoreaccount1"));
        assertThrows(IllegalArgumentException.class,()->LocalBlobEmulator.publicEndpoint("http://azurite:10000/devstoreaccount1"));
    }
    @Test void sasIsCreateOnlyOrReadOnlyHttpsScopedAndCached() {
        var service=mock(BlobServiceClient.class); var container=mock(BlobContainerClient.class); var blob=mock(BlobClient.class);
        when(service.getBlobContainerClient("media")).thenReturn(container);
        when(container.getBlobClient("assets/owner/photo.jpg")).thenReturn(blob);
        when(blob.getBlobUrl()).thenReturn("https://account.blob.core.windows.net/media/assets/owner/photo.jpg");
        var key=new UserDelegationKey().setSignedExpiry(OffsetDateTime.now().plusHours(1));
        Response<UserDelegationKey> response=mock(Response.class); when(response.getValue()).thenReturn(key);
        when(service.getUserDelegationKeyWithResponse(any(),any(),any(),any())).thenReturn(response);
        when(blob.generateUserDelegationSas(any(),eq(key))).thenReturn("signed");
        var storage=new AzureBlobStorage(service,"media",100);
        assertTrue(storage.createUploadUrl("assets/owner/photo.jpg","image/jpeg").endsWith("?signed"));
        storage.createAccessUrl("assets/owner/photo.jpg",true);
        var values=ArgumentCaptor.forClass(BlobServiceSasSignatureValues.class);
        verify(blob,times(2)).generateUserDelegationSas(values.capture(),eq(key));
        assertEquals("c",values.getAllValues().get(0).getPermissions());
        assertEquals("r",values.getAllValues().get(1).getPermissions());
        assertEquals("https",values.getValue().getProtocol().toString());
        assertEquals("attachment",values.getValue().getContentDisposition());
        assertTrue(values.getValue().getExpiryTime().isBefore(OffsetDateTime.now().plusSeconds(61)));
        verify(service,times(1)).getUserDelegationKeyWithResponse(any(),any(),any(),any());
        assertEquals("BlockBlob",storage.uploadHeaders().get("x-ms-blob-type"));
        assertThrows(IllegalArgumentException.class,()->storage.createUploadUrl("other/key","image/jpeg"));
    }

    @Test void uploadVerificationRejectsMissingOversizedAndMismatchedMedia() {
        var service=mock(BlobServiceClient.class); var container=mock(BlobContainerClient.class); var blob=mock(BlobClient.class);
        when(service.getBlobContainerClient("media")).thenReturn(container);
        when(container.getBlobClient("assets/photo.jpg")).thenReturn(blob);
        var properties=mock(BlobProperties.class); Response<BlobProperties> response=mock(Response.class);
        when(response.getValue()).thenReturn(properties);
        when(blob.getPropertiesWithResponse(any(),any(),any())).thenReturn(response);
        var storage=new AzureBlobStorage(service,"media",100);
        when(properties.getBlobSize()).thenReturn(10L); when(properties.getContentType()).thenReturn("image/jpeg");
        assertDoesNotThrow(()->storage.verifyUpload("assets/photo.jpg","image"));
        when(properties.getBlobSize()).thenReturn(101L);
        assertEquals(400,assertThrows(ResponseStatusException.class,()->storage.verifyUpload("assets/photo.jpg","image")).getStatusCode().value());
        when(properties.getBlobSize()).thenReturn(10L); when(properties.getContentType()).thenReturn("video/mp4");
        assertThrows(ResponseStatusException.class,()->storage.verifyUpload("assets/photo.jpg","image"));
        var missing=mock(BlobStorageException.class); when(missing.getStatusCode()).thenReturn(404);
        when(blob.getPropertiesWithResponse(any(),any(),any())).thenThrow(missing);
        assertEquals(409,assertThrows(ResponseStatusException.class,()->storage.verifyUpload("assets/photo.jpg","image")).getStatusCode().value());
    }

    @Test void productionClientBuildsWithoutAccountKeysAndValidatesAccountName() {
        assertDoesNotThrow(()->new AzureBlobStorage("mediameshdemo","media",100));
        assertThrows(IllegalArgumentException.class,()->new AzureBlobStorage("https://untrusted.example","media",100));
    }
}
