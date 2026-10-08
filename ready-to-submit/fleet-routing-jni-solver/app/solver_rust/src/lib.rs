use jni::JNIEnv;
use jni::objects::{JClass, JObject};
use jni::sys::{jlong, jint, jstring};
use lazy_static::lazy_static;
use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Mutex;

static NEXT_HANDLE: AtomicI64 = AtomicI64::new(1001);

#[derive(Debug, Clone)]
pub struct VrpPlan {
    pub id: i64,
    pub order_id: u32,
    pub departure_time: u64,
    pub weight: u64,
    pub lat: f64,
    pub lon: f64,
}

lazy_static! {
    static ref ACTIVE_PLANS: Mutex<HashMap<i64, VrpPlan>> = Mutex::new(HashMap::new());
}

#[no_mangle]
pub extern "system" fn Java_com_fleet_DispatchGateway_solveVrpNative(
    env: JNIEnv,
    _class: JClass,
    buffer_obj: JObject,
    _buffer_cap: jint,
) -> jlong {
    let buf_addr = match env.get_direct_buffer_address(&buffer_obj) {
        Ok(addr) => addr,
        Err(_) => return -1,
    };
    let buf_len = match env.get_direct_buffer_capacity(&buffer_obj) {
        Ok(cap) => cap,
        Err(_) => return -1,
    };

    if buf_len < 36 {
        return -1;
    }

    let slice = unsafe { std::slice::from_raw_parts(buf_addr, buf_len) };

    // Read payload fields:
    // bytes 0..4: order_id (u32, little endian)
    // bytes 4..12: departure_time (u64, expected little endian in Rust solver)
    // bytes 12..20: weight (u64, expected little endian in Rust solver)
    // bytes 20..28: lat (f64, IEEE 754)
    // bytes 28..36: lon (f64, IEEE 754)

    let order_id = u32::from_le_bytes(slice[0..4].try_into().unwrap());
    
    // Rust solver reads 8-byte timestamps and weights as little-endian bytes.
    // If Java wrote big-endian into DirectByteBuffer without calling .order(ByteOrder.LITTLE_ENDIAN),
    // these values will be corrupted.
    let departure_time = u64::from_le_bytes(slice[4..12].try_into().unwrap());
    let weight = u64::from_le_bytes(slice[12..20].try_into().unwrap());

    let lat_bits = u64::from_le_bytes(slice[20..28].try_into().unwrap());
    let lon_bits = u64::from_le_bytes(slice[28..36].try_into().unwrap());
    let lat = f64::from_bits(lat_bits);
    let lon = f64::from_bits(lon_bits);

    let handle_id = NEXT_HANDLE.fetch_add(1, Ordering::SeqCst);

    let plan = VrpPlan {
        id: handle_id,
        order_id,
        departure_time,
        weight,
        lat,
        lon,
    };

    let mut map = ACTIVE_PLANS.lock().unwrap();
    map.insert(handle_id, plan);

    handle_id
}

#[no_mangle]
pub extern "system" fn Java_com_fleet_DispatchGateway_releaseVrpPlanNative(
    _env: JNIEnv,
    _class: JClass,
    handle: jlong,
) -> jint {
    let mut map = ACTIVE_PLANS.lock().unwrap();
    if map.remove(&handle).is_some() {
        0 // Success
    } else {
        -1 // Handle not found
    }
}

#[no_mangle]
pub extern "system" fn Java_com_fleet_DispatchGateway_getActivePlanCountNative(
    _env: JNIEnv,
    _class: JClass,
) -> jint {
    let map = ACTIVE_PLANS.lock().unwrap();
    map.len() as jint
}

#[no_mangle]
pub extern "system" fn Java_com_fleet_DispatchGateway_getPlanDepartureTimeNative(
    _env: JNIEnv,
    _class: JClass,
    handle: jlong,
) -> jlong {
    let map = ACTIVE_PLANS.lock().unwrap();
    if let Some(plan) = map.get(&handle) {
        plan.departure_time as jlong
    } else {
        -1
    }
}
