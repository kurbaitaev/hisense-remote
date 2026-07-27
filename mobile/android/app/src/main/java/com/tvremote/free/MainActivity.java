package com.tvremote.free;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(RokuDiscoverPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
